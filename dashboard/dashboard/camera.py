"""On-demand local JPEG input, independent H.264/fMP4 streams for remote viewers."""
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
import math
import time
import uuid

from aiohttp import web
from .browser_traffic import ViewerWebSocket
from .traffic import BrowserTraffic
from .video_encoder import H264Encoder, PROFILES
from .topic_groups import camera_source_topic


@dataclass
class Stream:
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    jpeg: bytes | None = None
    received: float = 0
    captured: float = 0
    version: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    viewers: dict = field(default_factory=dict)


class CameraHub:
    STALE_SECONDS = 3
    MAX_FRAME_BYTES = 8 * 1024 * 1024
    MAX_IN_FLIGHT = 4
    ACK_TIMEOUT = 3

    def __init__(self, groups, browser=None):
        self.groups = groups
        self.browser = browser if browser is not None else BrowserTraffic()
        self.streams = {}
        self.sockets = set()

    def allowed(self, mode, topic):
        return (isinstance(topic, str) and not topic.startswith(('/lidar/', '/ouster/'))
                and topic in self.groups.image_topics(mode))

    async def demand(self, request):
        allowed = {camera_source_topic(mode, name)
                   for mode in self.groups.modes for name in self.groups.image_topics(mode)
                   if self.allowed(mode, name)}
        return web.json_response({'settings': {**self.groups.camera, 'transport': 'h264'}, 'streams': [
            {'topic': topic, 'token': stream.token, 'fps': max(stream.viewers.values())}
            for topic, stream in self.streams.items() if topic in allowed and stream.viewers
        ]}, headers={'Cache-Control': 'no-store'})

    async def receive_frame(self, request):
        topic, token = request.query.get('topic'), request.query.get('token')
        stream = self.streams.get(topic)
        if stream is None or stream.token != token:
            raise web.HTTPConflict(text='Stream is no longer requested')
        if request.content_type != 'image/jpeg':
            raise web.HTTPBadRequest(text='Expected JPEG local camera input')
        jpeg = await request.read()
        if not 4 <= len(jpeg) <= self.MAX_FRAME_BYTES or not (jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')):
            raise web.HTTPBadRequest(text='Invalid JPEG')
        now = time.monotonic()
        try:
            captured = float(request.headers.get('X-Capture-Monotonic', now))
            if not math.isfinite(captured) or not 0 <= now-captured <= 3:
                raise ValueError()
        except ValueError:
            raise web.HTTPBadRequest(text='Invalid local frame timestamp')
        if self.streams.get(topic) is not stream:
            raise web.HTTPConflict(text='Stream changed')
        stream.jpeg, stream.received, stream.captured = jpeg, now, captured
        stream.version += 1; stream.changed.set()
        return web.Response(status=204)

    async def video(self, request):
        topic, mode = request.query.get('topic', ''), request.query.get('mode', '')
        if not self.allowed(mode, topic):
            raise web.HTTPBadRequest(text='Image topic is not configured for this mode')
        try:
            value = request.query.get('fps', str(self.groups.camera['fps']))
            if not value.isascii() or not value.isdigit(): raise ValueError()
            fps = int(value)
            if fps not in PROFILES: raise ValueError()
        except ValueError:
            raise web.HTTPBadRequest(text='FPS must be 5, 10, 15, 20, 25 or 30')
        ws = ViewerWebSocket(self.browser, heartbeat=10, compress=False, max_msg_size=128)
        await ws.prepare(request)
        source_topic = camera_source_topic(mode, topic)
        stream = self.streams.setdefault(source_topic, Stream())
        stream.viewers[ws] = fps; self.sockets.add(ws)
        encoder = H264Encoder(fps, self.groups.camera['max_width'])
        worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='h264-viewer')
        loop = asyncio.get_running_loop()
        in_flight = deque()

        async def send_frames():
            version, next_frame, last_status, sent_init = 0, 0, 0, False
            while not ws.closed and self.allowed(mode, topic):
                now = time.monotonic()
                if in_flight and now-in_flight[0] >= self.ACK_TIMEOUT: return
                fresh = stream.jpeg is not None and now-stream.captured < self.STALE_SECONDS
                if fresh and stream.version != version and now >= next_frame and len(in_flight) < self.MAX_IN_FLIGHT:
                    version = stream.version
                    # Only the latest unencoded source is retained. No accumulating video queue.
                    next_frame = max(next_frame + 1/fps, now)
                    data = await loop.run_in_executor(worker, encoder.encode, stream.jpeg, stream.captured)
                    if data:
                        if not sent_init:
                            await ws.send_json({'type': 'init', 'mime': encoder.mime, 'fps': fps,
                                'bitrate_kbps': encoder.kbps, 'width': encoder.width, 'height': encoder.height})
                            sent_init = True
                        in_flight.append(time.monotonic())
                        await asyncio.wait_for(ws.send_bytes(data), 2)
                    continue
                if now-last_status >= 1:
                    await asyncio.wait_for(ws.send_json({'type':'status', 'error': None if fresh else '영상 수신 대기',
                                                        'fps':fps, 'bitrate_kbps':encoder.kbps}), 2)
                    last_status = now
                stream.changed.clear()
                waiting_for_pace = fresh and stream.version != version and len(in_flight) < self.MAX_IN_FLIGHT
                delay = min(.1, max(.002, next_frame-now)) if waiting_for_pace else .1
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stream.changed.wait(), delay)

        async def send():
            try:
                await send_frames()
            except (ConnectionError, asyncio.TimeoutError):
                pass
            except Exception as error:
                if not ws.closed:
                    with suppress(ConnectionError):
                        await ws.send_json({'type':'error','error':'H.264 영상 처리 오류: '+str(error)[:180]})
            finally:
                await ws.close()

        sender = asyncio.create_task(send())
        try:
            async for message in ws:
                if message.type == web.WSMsgType.TEXT and message.data == 'ack':
                    if in_flight: in_flight.popleft(); stream.changed.set()
                elif message.type == web.WSMsgType.ERROR: break
        finally:
            self.sockets.discard(ws); stream.viewers.pop(ws, None)
            if not stream.viewers and self.streams.get(source_topic) is stream:
                del self.streams[source_topic]
            # Let a bounded encoder call finish before closing its context in the same worker path.
            await ws.close()
            await asyncio.gather(sender, return_exceptions=True)
            await loop.run_in_executor(worker, encoder.close)
            worker.shutdown(wait=True)
        return ws

    async def script(self, request):
        return web.Response(body=Path(__file__).with_name('camera-player.js').read_bytes(),
                            content_type='application/javascript', headers={'Cache-Control':'no-cache'})

    async def shutdown(self, app):
        await asyncio.gather(*(ws.close(code=1001) for ws in list(self.sockets)))

    def add_routes(self, app):
        app.router.add_get('/ws/camera', self.video)
        app.router.add_get('/api/camera/demand', self.demand)
        app.router.add_post('/api/camera/frame', self.receive_frame)
        app.router.add_get('/camera-player.js', self.script)
        app.on_shutdown.append(self.shutdown)
