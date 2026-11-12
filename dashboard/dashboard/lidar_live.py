"""Replaceable, bounded LiDAR map; binary deltas with one acknowledged batch in flight."""
import asyncio
from array import array
from collections import OrderedDict
import json
import math
import struct
import sys
import time
from aiohttp import web
from .browser_traffic import ViewerWebSocket

MAX_POINTS = 500_000
MAX_PATH = 20_000
VIEW_POINTS = 3_750
VIEW_PATH = 100


def encode(header, points=b'', path=b''):
    meta = json.dumps(header, separators=(',', ':'), ensure_ascii=False).encode()
    return struct.pack('<I', len(meta)) + meta + points + path


def decode(data):
    if len(data) < 4:
        raise ValueError('Missing header')
    size, = struct.unpack_from('<I', data)
    if not 0 < size <= 8192 or 4 + size > len(data):
        raise ValueError('Invalid header')
    meta = json.loads(data[4:4+size])
    if not isinstance(meta, dict):
        raise ValueError('Invalid header')
    return meta, data[4+size:]


class LidarLive:
    def __init__(self):
        self.session = None
        self.points = OrderedDict()
        self.source_revision = self.revision = 0
        self.path = bytearray()
        self.status = {}
        self.received = None
        self.sockets = set()

    def cursor(self):
        return {'session': self.session, 'points': len(self.points), 'revision': self.source_revision, 'path': len(self.path)//12}

    def update(self, payload):
        h, body = decode(payload)
        if not isinstance(h.get('session'), str) or not 1 <= len(h['session']) <= 64:
            raise ValueError('Invalid session')
        for k, limit in [('point_start',2**53-1),('point_end',2**53-1),('path_start',MAX_PATH),('point_count',20000),('path_count',1000)]:
            if type(h.get(k)) is not int or not 0 <= h[k] <= limit:
                raise ValueError('Invalid count')
        if len(body) != 16*h['point_count']+12*h['path_count']:
            raise ValueError('Invalid point bytes')
        if h['path_start']+h['path_count']>MAX_PATH:
            raise ValueError('Map capacity exceeded')
        split=h['point_count']*16
        records=list(struct.iter_unpack('<Ifff',body[:split]))
        if len({r[0] for r in records})!=len(records) or any(r[0]>=MAX_POINTS for r in records):
            raise ValueError('Invalid point ID')
        if h['point_end']<h['point_start']+h['point_count'] or (not records and h['point_end']!=h['point_start']):
            raise ValueError('Invalid revision')
        values = array('f'); values.frombytes(body[split:])
        if sys.byteorder != 'little': values.byteswap()
        if any(not math.isfinite(v) or abs(v)>1e7 for r in records for v in r[1:]) or any(not math.isfinite(v) or abs(v)>1e7 for v in values):
            raise ValueError('Invalid coordinate')
        status = h.get('status', {})
        if not isinstance(status, dict): raise ValueError('Invalid status')
        cleaned = {}
        for key in ('scans','dropped','processing_ms','age_s','stamp','queue'):
            value = status.get(key,0)
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:
                raise ValueError('Invalid status value')
            cleaned[key] = value
        cleaned['message'] = str(status.get('message',''))[:160]
        cleaned['limited'] = bool(status.get('limited',False))
        changed = h['session'] != self.session
        expected = {'revision':0,'path':0} if changed else self.cursor()
        if h['point_start'] != expected['revision'] or h['path_start'] != expected['path']:
            return False
        if changed:
            self.points.clear(); self.path.clear(); self.session=h['session'];self.revision=0
        for index,record in enumerate(records):
            ident=record[0];self.revision+=1
            self.points[ident]=(self.revision,body[index*16:(index+1)*16]);self.points.move_to_end(ident)
        self.source_revision=h['point_end'];self.path.extend(body[split:])
        self.status=cleaned; self.received=time.monotonic()
        return True

    def packet(self, session, point, path):
        reset = session != self.session or point > self.revision or path > len(self.path)//12
        if reset: point=path=0
        records=[];end=point
        for revision,record in self.points.values():
            if revision<=point:continue
            records.append(record);end=revision
            if len(records)>=VIEW_POINTS:break
        chunk=b''.join(records)
        trace=bytes(self.path[path*12:(path+VIEW_PATH)*12])
        age = (time.monotonic()-self.received) if self.received is not None else 1e9
        h={'session':self.session,'reset':reset,'point_start':point,'path_start':path,
           'point_end':end,'point_count':len(chunk)//16,'path_count':len(trace)//12,
           'total_points':len(self.points),'total_path':len(self.path)//12,
           'status':self.status,'active':age+self.status.get('age_s',1e9)<3,
           'voxel_m':.5,'min_hits':2}
        return h, encode(h,chunk,trace)

    def add_routes(self, app, browser):
        async def ingest(request):
            try:
                accepted=self.update(await request.read())
            except (ValueError,TypeError,OverflowError):
                raise web.HTTPBadRequest(text='Invalid LiDAR report')
            return web.json_response(self.cursor(),status=200 if accepted else 409)

        async def state(request):
            return web.json_response(self.cursor())

        async def stream(request):
            ws=ViewerWebSocket(browser,heartbeat=20,compress=False,max_msg_size=2048)
            await ws.prepare(request);self.sockets.add(ws)
            session=None;point=path=0
            try:
                while not ws.closed:
                    started=time.monotonic()
                    h,payload=self.packet(session,point,path)
                    await asyncio.wait_for(ws.send_bytes(payload),timeout=5)
                    response=await ws.receive(timeout=5)
                    if response.type != web.WSMsgType.TEXT: break
                    try: ack=json.loads(response.data)
                    except ValueError: break
                    next_point=h['point_end'];next_path=h['path_start']+h['path_count']
                    if not isinstance(ack,dict) or ack.get('session')!=h['session'] or ack.get('points')!=next_point or ack.get('path')!=next_path:
                        break
                    session=h['session'];point=next_point;path=next_path
                    await asyncio.sleep(max(0,1-(time.monotonic()-started)))
            except (ConnectionError,asyncio.TimeoutError):
                pass
            finally:
                self.sockets.discard(ws);await ws.close()
            return ws

        async def shutdown(app):
            await asyncio.gather(*(ws.close(code=1001) for ws in list(self.sockets)))
        app.router.add_post('/api/ros/lidar-map',ingest)
        app.router.add_get('/api/ros/lidar-map/state',state)
        app.router.add_get('/ws/lidar-map',stream)
        app.on_shutdown.append(shutdown)
