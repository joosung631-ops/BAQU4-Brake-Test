"""Bounded GPS replay history and per-viewer incremental delivery."""
import asyncio
import uuid
# 이전: from collections import deque
import math
import time
from aiohttp import web
from .browser_traffic import ViewerWebSocket


class GPSLive:
    def __init__(self, origin):
        self.origin = origin
        self.session = None
        # 이전: self.points = deque(maxlen=10000)
        self.points = []
        self.stream_id = uuid.uuid4().hex
        self.last_seq = 0
        self.received = None
        self.latest = None
        self.sockets = set()

    def update(self, data, now=None):
        if not isinstance(data, dict) or not isinstance(data.get('session'), str) or not 1 <= len(data['session']) <= 64:
            raise ValueError('invalid session')
        rows = data.get('points')
        if not isinstance(rows, list) or len(rows) > 256:
            raise ValueError('invalid points')
        checked = []
        previous = 0
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('invalid point')
            seq = row.get('seq')
            if type(seq) is not int or seq <= previous:
                raise ValueError('invalid sequence')
            previous = seq
            for key in ('t', 'lat', 'lon'):
                value = row.get(key)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError('invalid coordinate')
            if not -90 <= row['lat'] <= 90 or not -180 <= row['lon'] <= 180:
                raise ValueError('invalid coordinate')
            # 이전 날짜 제한: 다른 날짜 rosbag도 표시하도록 해제.
            # if not 1789830000 <= row['t'] < 1789916400:
            #     raise ValueError('only September 20 KST replay is accepted')
            if row['t'] < 0:
                raise ValueError('negative GPS timestamp')
            if type(row.get('status')) is not int or row['status'] not in (0, 1, 2):
                raise ValueError('invalid fix')
            quality = row.get('quality')
            if quality is not None and (type(quality) is not int or not 0 <= quality <= 8):
                raise ValueError('invalid quality')
            checked.append({**{k:row[k] for k in ('seq','t','lat','lon','status')}, 'quality':quality})
        if data['session'] != self.session:
            self.session = data['session']
            # 이전: self.points.clear() — bag 변경/반복 시에도 유지합니다.
            self.last_seq = 0
            self.received = None
        for row in checked:
            if row['seq'] <= self.last_seq:
                continue
            row['break'] = row['seq'] != self.last_seq + 1
            self.last_seq = row['seq']
            row['seq'] = len(self.points) + 1
            self.points.append(row)
            self.received = time.monotonic() if now is None else now
            self.latest = dict(row)

    def current(self, now=None):
        now = time.monotonic() if now is None else now
        age = max(0., now-self.received) if self.received is not None else None
        return {'point':self.latest, 'age_s':age, 'active':age is not None and age<3,
                'source_session':self.session}

    def packet(self, session, sequence, now=None):
        # 이전에는 bag/source session 변경 시 브라우저에 초기화를 지시했습니다.
        reset = session != self.stream_id or sequence > len(self.points)
        start = 0 if reset else sequence
        points = self.points[start:start+512]
        now = time.monotonic() if now is None else now
        return {'session':self.stream_id, 'seq':points[-1]['seq'] if points else start,
                'reset':bool(reset), 'points':points, 'origin':self.origin,
                'active':self.received is not None and now-self.received < 3}

    def clear(self):
        self.points.clear()
        self.stream_id = uuid.uuid4().hex
        # Source watermark remains: repeated upload batches must not restore erased points.

    def add_routes(self, app, browser):
        async def receive(request):
            try:
                self.update(await request.json())
            except (ValueError, TypeError):
                raise web.HTTPBadRequest(text='Invalid GPS report')
            return web.Response(status=204)

        async def clear(request):
            if request.headers.get('X-Dashboard-Control') != '1':
                raise web.HTTPForbidden()
            self.clear()
            return web.Response(status=204)

        async def current(request):
            return web.json_response(self.current(), headers={'Cache-Control':'no-store'})

        async def stream(request):
            ws = ViewerWebSocket(browser, heartbeat=20, compress=False)
            await ws.prepare(request)
            self.sockets.add(ws)
            async def send():
                session, seq = None, 0
                try:
                    while not ws.closed:
                        packet = self.packet(session, seq)
                        await asyncio.wait_for(ws.send_json(packet), timeout=5)
                        session, seq = packet['session'], packet['seq']
                        await asyncio.sleep(.5)
                except (ConnectionError, asyncio.TimeoutError):
                    await ws.close()
            sender = asyncio.create_task(send())
            try:
                async for _ in ws:
                    pass
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
                self.sockets.discard(ws)
            return ws

        async def shutdown(app):
            await asyncio.gather(*(ws.close(code=1001) for ws in list(self.sockets)))
        app.router.add_post('/api/ros/gps', receive)
        app.router.add_post('/api/gps/clear', clear)
        app.router.add_get('/ws/gps', stream)
        app.router.add_get('/api/gps/current', current)
        app.on_shutdown.append(shutdown)
