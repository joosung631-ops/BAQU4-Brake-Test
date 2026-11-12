"""Bounded three-sensor brake viewer. ROS stays in the main container."""
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import json
import ipaddress
import os
from pathlib import Path
import struct
import time

import aiohttp
from aiohttp import web
from .browser_traffic import ViewerWebSocket
from .video_encoder import H264Encoder
from .bandwidth import ViewerBudget
from .steering_preview import PredictionStore

SOURCE = os.environ.get('BRAKE_SOURCE_URL', 'http://127.0.0.1:8771')
LIDAR_HZ = 10
MAX_VIEW_POINTS = 3000
MAX_VIEW_CONES = 64


def camera_profile(rate, viewers, lidar_points):
    """Reserve 10Hz LiDAR and control traffic first; use the rest for video."""
    # Up to 64 observed boxes (14B each) accompany LiDAR at 10Hz. The
    # Shared box quota, four 3D lines and status reserve precede video allocation.
    remaining = rate / viewers - lidar_points * 6 * LIDAR_HZ * 1.08 - 20000 / viewers
    kbps = max(100, min(1800, int(max(0, remaining) * .95 * 8 / 1000 / 50) * 50))
    fps = 30 if kbps >= 1000 else 25 if kbps >= 700 else 20 if kbps >= 450 else 15 if kbps >= 250 else 10
    return fps, kbps


def sample_cloud(cloud, limit):
    count = min(len(cloud) // 6, limit)
    if not count: return b''
    size = len(cloud) // 6
    # Uniform indices across every distance band; never truncate the far band.
    return b''.join(cloud[(i*size//count)*6:(i*size//count)*6+6] for i in range(count))


def cone_packet(header, limit):
    """Valid byte + count + centimetre center/size/point-count records."""
    valid = bool(header.get('fresh', {}).get('cones'))
    rows = header.get('cones', {}).get('items', [])[:limit] if valid else []
    packed = bytearray(struct.pack('<BH', valid, len(rows)))
    for row in rows:
        if (len(row) != 7 or any(type(v) is not int for v in row) or
                any(abs(v) > 5000 for v in row[:3]) or
                any(not 0 <= v <= 500 for v in row[3:6]) or not 3 <= row[6] <= 600):
            raise ValueError('라바콘 관측 크기 오류')
        packed.extend(struct.pack('<6hH', *row))
    return bytes(packed)


def line_packet(header):
    """L1 + mask + at most four 3D endpoint pairs, in cm (51 bytes)."""
    course = header.get('cones', {}).get('course', {}) if header.get('fresh', {}).get('cones') else {}
    lines = course.get('lines', {})
    mask, body = 0, bytearray()
    for i, name in enumerate(('left', 'right', 'center', 'stop')):
        if name not in lines:
            continue
        row = lines[name].get('points_cm', [])
        if len(row) != 6 or any(type(v) is not int or abs(v) > 6000 for v in row):
            raise ValueError('코스 선 좌표 오류')
        mask |= 1 << i
        body.extend(struct.pack('<6h', *row))
    return b'L1' + bytes([mask]) + body


def stop_packet(header):
    """S1 + state, then distance/cells/span and endpoints (at most 21B)."""
    row = header.get('stop_row', {}) if header.get('fresh', {}).get('stop_row') else {}
    state = {'candidate': 1, 'confirmed': 2}.get(row.get('state'), 0)
    if not state:
        return b'S1\0'
    points = row.get('points_cm', [])
    values = [row.get('distance_cm'), row.get('support_cells'), row.get('span_cm')]
    if (len(points) != 6 or any(type(v) is not int or abs(v) > 6000 for v in points)
            or any(type(v) is not int for v in values)
            or not 200 <= values[0] <= 4500 or not 3 <= values[1] <= 64 or not 150 <= values[2] <= 800):
        raise ValueError('원거리 정지열 관측 오류')
    return b'S1' + struct.pack('<B3H6h', state, *values, *points)


def unpack(data):
    if len(data) < 4: raise ValueError('센서 패킷 없음')
    size, = struct.unpack_from('<I', data)
    if not 0 < size <= 16384 or len(data) < 4 + size: raise ValueError('센서 헤더 오류')
    h = json.loads(data[4:4+size]); a, b = h['cloud_bytes'], h['jpeg_bytes']
    if type(a) is not int or type(b) is not int or not 0 <= a <= 24000 or a % 6 or not 0 <= b <= 8_000_000 or len(data) != 4 + size + a + b:
        raise ValueError('센서 패킷 크기 오류')
    return h, data[4+size:4+size+a], data[4+size+a:]


def add_routes(app, browser):
    sockets = set()
    prediction=PredictionStore()
    if not hasattr(browser, 'budget'): browser.budget = ViewerBudget()

    async def receive_prediction(request):
        try:local=ipaddress.ip_address(request.remote or '').is_loopback
        except ValueError:local=False
        if not local:raise web.HTTPForbidden()
        if request.content_type!='application/json' or request.content_length is None or request.content_length>2048:
            raise web.HTTPBadRequest()
        try:prediction.put(await request.json())
        except (ValueError,TypeError):raise web.HTTPBadRequest()
        return web.json_response({'ok':True})

    async def proxy(request):
        action = request.match_info['action']; data = None
        if request.method == 'POST':
            if request.headers.get('X-Dashboard-Control') != '1' or request.content_type != 'application/json':
                raise web.HTTPForbidden()
            if request.content_length is None or request.content_length > 2048: raise web.HTTPBadRequest()
            try: data = await request.json()
            except ValueError: raise web.HTTPBadRequest()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as client:
                async with client.request(request.method, SOURCE + '/' + action, json=data,
                                          headers={'X-Dashboard-Control': '1'}) as response:
                    return web.json_response(await response.json(), status=response.status, headers={'Cache-Control':'no-store'})
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return web.json_response({'error':'main의 제동 시각화 수집기에 연결할 수 없습니다.'}, status=503)

    async def asset(request):
        name = request.path[1:]
        return web.Response(body=Path(__file__).with_name(name).read_bytes(),
                            content_type='text/css' if name.endswith('.css') else 'application/javascript',
                            headers={'Cache-Control': 'no-cache'})

    async def stream(request):
        if len(sockets) >= 4:
            raise web.HTTPServiceUnavailable(text='제동 화면은 최대 4개 접속까지 지원합니다.')
        ws = ViewerWebSocket(browser, heartbeat=10, compress=False, max_msg_size=128)
        await ws.prepare(request); sockets.add(ws)
        encoder = None; encoding_profile = None; epoch = None
        worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='brake-video')
        loop = asyncio.get_running_loop()
        cursor = {}; last_status = 0; next_cloud = next_video = 0; last_profile = 0
        cloud_task = video_task = None
        latest_cloud = latest_jpeg = None
        cloud_sample = None
        first_jpeg_time = None
        cloud_version = video_version = -1
        lidar_points = 1500
        flights = {1: deque(), 2: deque()}; order = deque()
        sent_clouds = deque(maxlen=40)
        render_epoch = 0
        prediction_key=None;drive_key=None;last_prediction=0

        async def acknowledgements():
            try:
                while not ws.closed:
                    reply = await ws.receive()
                    if reply.type != web.WSMsgType.TEXT: break
                    if reply.data == 'ack':
                        if not order: break
                        kind = order[0][0]
                    elif reply.data.startswith(('ack:1:', 'ack:2:')):
                        fields = reply.data.split(':')
                        if len(fields) != 3 or not fields[2].isdigit(): break
                        if int(fields[2]) != render_epoch: continue
                        kind = int(fields[1])
                    elif reply.data in ('ack:1', 'ack:2'):
                        kind = int(reply.data[-1])
                    else: break
                    if not flights[kind]: continue
                    record = flights[kind].popleft(); order.remove(record)
            finally:
                await ws.close()

        async def binary(kind, payload):
            record = (kind, time.monotonic(), render_epoch)
            flights[kind].append(record); order.append(record)
            await asyncio.wait_for(ws.send_bytes(bytes([kind]) + payload, priority=kind == 1), 5)
            if kind == 1: sent_clouds.append(time.monotonic())

        async def video_frame(image, owner):
            data = await loop.run_in_executor(worker, owner.encode, image, time.monotonic())
            if data:
                if owner.frames == 1: await ws.send_json({'type':'video-init', 'mime':owner.mime})
                await binary(2, data)

        reader = asyncio.create_task(acknowledgements())

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as client:
                while not ws.closed:
                    started = time.monotonic()
                    for task in (cloud_task, video_task):
                        if task is not None and task.done(): task.result()
                    if any(queue and started - queue[0][1] > 5 for queue in flights.values()):
                        raise ConnectionError('viewer acknowledgement timeout')
                    try:
                        async with client.get(SOURCE + '/snapshot', params=cursor) as response:
                            if response.status != 200: raise ValueError('센서 수집기 응답 오류')
                            h, cloud, jpeg = unpack(await response.read())
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
                        await ws.send_json({'type':'status', 'phase':'error', 'error':str(error)[:160]})
                        await asyncio.sleep(1); continue
                    viewers = max(1, len(sockets))
                    epoch_changed = h['session'] != epoch
                    if epoch_changed:
                        for task in (cloud_task, video_task):
                            if task: task.cancel()
                        await asyncio.gather(*(t for t in (cloud_task, video_task) if t), return_exceptions=True)
                        cloud_task = video_task = None
                        latest_cloud = latest_jpeg = None
                        cloud_sample = None
                        first_jpeg_time = None
                        cloud_version = video_version = -1; next_cloud = next_video = 0
                        sent_clouds.clear()
                    point_limit = max(500, MAX_VIEW_POINTS // viewers)
                    if cloud or (h['versions']['cloud'] and h.get('cloud', {}).get('point_count') == 0):
                        cloud_sample = sample_cloud(cloud, point_limit)
                        lidar_points = len(cloud_sample) // 6
                    if cloud_sample is not None:
                        # A paused scan can finish detection after its cloud
                        # was sent. Publish that update without advancing time.
                        key = (h['versions']['cloud'], h['versions'].get('cones', 0), bool(h.get('fresh', {}).get('cones')),
                               h['versions'].get('stop_row', 0), bool(h.get('fresh', {}).get('stop_row')))
                        latest_cloud = (key, struct.pack('<I', len(cloud_sample)//6) + cloud_sample +
                                        cone_packet(h, max(1, MAX_VIEW_CONES // viewers)) + line_packet(h) + stop_packet(h))
                    if jpeg:
                        if latest_jpeg is None: first_jpeg_time = started
                        latest_jpeg = (h['versions']['camera'], jpeg)
                    desired = camera_profile(browser.budget.rate, viewers, lidar_points)
                    change_profile = (encoding_profile is None or
                        (encoder.frames == 0 and desired != encoding_profile) or (started - last_profile >= 5 and
                        (desired[0] != encoding_profile[0] or abs(desired[1] - encoding_profile[1]) >= max(150, encoding_profile[1] * .25)))
                        )
                    video_idle = video_task is None or video_task.done()
                    if epoch_changed or (change_profile and video_idle):
                        # Cancel old queued writes before changing the render
                        # generation; late ACKs must not release new frames.
                        for task in (cloud_task, video_task):
                            if task: task.cancel()
                        await asyncio.gather(*(t for t in (cloud_task, video_task) if t), return_exceptions=True)
                        cloud_task = video_task = None
                        for queue in flights.values(): queue.clear()
                        order.clear(); render_epoch += 1
                        if encoder: await loop.run_in_executor(worker, encoder.close)
                        encoder = H264Encoder(desired[0], 640, kbps=desired[1])
                        epoch, encoding_profile = h['session'], desired
                        await ws.send_json({'type':'reset', 'session':epoch, 'render_epoch':render_epoch})
                        video_version = -1; last_profile = started
                    cursor = {'session':epoch, **{k:str(v) for k,v in h['versions'].items()}}
                    if started - last_status >= 1:
                        recent = [t for t in sent_clouds if started-t < 3]
                        lidar_rate = (len(recent)-1)/(recent[-1]-recent[0]) if len(recent)>1 else 0
                        cone_info = {k:v for k,v in h.get('cones', {}).items() if k != 'items'}
                        cone_info['shown'] = min(len(h.get('cones', {}).get('items', [])), MAX_VIEW_CONES // viewers) if h.get('fresh', {}).get('cones') else 0
                        await ws.send_json({**h, 'cones':cone_info, 'type':'status', 'budget':browser.budget.snapshot(), 'viewers':viewers,
                                            'video_fps':encoding_profile[0], 'video_kbps':encoding_profile[1],
                                            'lidar_hz':round(lidar_rate,1), 'lidar_target_hz':LIDAR_HZ,
                                            'lidar_max_points':point_limit, 'hour_target_bytes':1_000_000_000})
                        last_status = started
                    if started-last_prediction>=.1:
                        preview=prediction.snapshot() if h.get('mode')=='live' else None
                        # Drive faults must remain visible even when the cloud is lost.
                        telemetry=preview if preview and 'drive' in preview else None
                        telemetry_key=(h['session'],None if telemetry is None else (telemetry['session'],telemetry['seq']))
                        if telemetry_key!=drive_key:
                            await ws.send_json({'type':'drive-status','value':{k:telemetry[k] for k in ('speed_mps','brake','publish_cmd','drive')} if telemetry else None})
                            drive_key=telemetry_key
                        stamp=h.get('cloud',{}).get('stamp')
                        if preview is not None and (not h.get('fresh',{}).get('cloud') or stamp is None or abs(preview['cloud_stamp_s']-stamp)>.5):
                            preview=None
                        key=(h['session'],None if preview is None else (preview['session'],preview['seq']))
                        if key!=prediction_key:
                            await ws.send_json({'type':'prediction','value':{k:v for k,v in preview.items() if k!='drive'} if preview else None})
                            prediction_key=key
                        last_prediction=started
                    if (latest_cloud and latest_cloud[0] != cloud_version and started >= next_cloud
                            and (cloud_task is None or cloud_task.done()) and len(flights[1]) < 2):
                        cloud_version, selected = latest_cloud
                        cloud_task = asyncio.create_task(binary(1, selected))
                        next_cloud = max(next_cloud+1/LIDAR_HZ, started)
                    prime = encoder.frames < max(6, encoding_profile[0]//2) and h.get('fresh', {}).get('camera')
                    # Get the first LiDAR sample before selecting the initial
                    # camera budget. Avoid a needless video restart at 5s.
                    camera_ready = latest_cloud is not None or (first_jpeg_time is not None and started-first_jpeg_time >= .25)
                    if (latest_jpeg and camera_ready and (latest_jpeg[0] != video_version or prime) and started >= next_video
                            and (video_task is None or video_task.done()) and len(flights[2]) < 3):
                        video_version, image = latest_jpeg
                        video_task = asyncio.create_task(video_frame(image, encoder))
                        next_video = max(next_video+1/encoding_profile[0], started)
                    await asyncio.sleep(max(.002, .01 - (time.monotonic()-started)))
        except (ConnectionError, asyncio.TimeoutError, aiohttp.ClientError): pass
        except Exception as error:
            with suppress(ConnectionError): await ws.send_json({'type':'status','phase':'error','error':str(error)[:200]})
        finally:
            sockets.discard(ws)
            for task in (reader, cloud_task, video_task):
                if task: task.cancel()
            await asyncio.gather(*(t for t in (reader, cloud_task, video_task) if t), return_exceptions=True)
            if encoder: await loop.run_in_executor(worker, encoder.close)
            worker.shutdown(wait=False)
            await ws.close()
        return ws

    async def shutdown(_):
        await asyncio.gather(*(ws.close(code=1001) for ws in list(sockets)))
    app.on_shutdown.append(shutdown)
    app.router.add_get('/api/brake/{action:bags}', proxy)
    app.router.add_post('/api/brake/{action:control}', proxy)
    app.router.add_get('/brake.js', asset)
    app.router.add_get('/prediction.js', asset)
    app.router.add_get('/brake.css', asset)
    app.router.add_get('/ws/brake', stream)
    app.router.add_post('/api/brake/prediction', receive_prediction)
