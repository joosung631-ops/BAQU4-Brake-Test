import asyncio
import io
import json
from pathlib import Path
import struct
import time
import unittest
from unittest.mock import patch

import av
from aiohttp import web, WSMsgType
from aiohttp.test_utils import TestClient, TestServer
from dashboard.bandwidth import ViewerBudget
from dashboard.brake import add_routes, unpack, camera_profile, sample_cloud, cone_packet, line_packet, stop_packet
from dashboard.traffic import BrowserTraffic


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    def test_stop_evidence_has_bounded_atomic_state_and_clears_when_stale(self):
        h={'fresh':{'stop_row':True},'stop_row':{'state':'candidate','distance_cm':4000,
           'support_cells':3,'span_cm':240,'points_cm':[-4000,-120,-110,-4000,120,-110]}}
        data=stop_packet(h)
        self.assertEqual(len(data),21)
        self.assertEqual(data[:3],b'S1\x01')
        self.assertEqual(struct.unpack_from('<3H',data,3),(4000,3,240))
        h['stop_row']['state']='confirmed';self.assertEqual(stop_packet(h)[:3],b'S1\x02')
        h['fresh']['stop_row']=False;self.assertEqual(stop_packet(h),b'S1\0')
        h['fresh']['stop_row']=True;h['stop_row']['support_cells']=1
        with self.assertRaises(ValueError):stop_packet(h)

    async def test_concurrent_senders_share_rate_and_rolling_window(self):
        budget = ViewerBudget(rate=20_000, burst=1000)
        started = time.monotonic()
        await asyncio.gather(*(budget.acquire(2000) for _ in range(4)))
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, .34)
        self.assertLessEqual(8000, 1000 + elapsed * 20_000 + 1)
        self.assertEqual(budget.snapshot()['last_hour_bytes'], 8000)
        with patch('dashboard.bandwidth.time.monotonic', return_value=time.monotonic()+3602):
            self.assertEqual(budget.snapshot()['last_hour_bytes'], 0)

    async def test_cancelled_wait_does_not_overspend(self):
        budget = ViewerBudget(rate=100, burst=100)
        await budget.acquire(100)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(budget.acquire(100), .01)
        self.assertEqual(budget.snapshot()['total_bytes'], 100)

    async def test_lidar_priority_precedes_waiting_video_and_cancellation_releases(self):
        budget=ViewerBudget(rate=10_000,burst=1000)
        await budget.acquire(1000)
        finished=[]
        async def send(label,priority):
            await budget.acquire(1000,priority=priority);finished.append(label)
        video=asyncio.create_task(send('video',False));await asyncio.sleep(.01)
        lidar=asyncio.create_task(send('lidar',True))
        await asyncio.gather(video,lidar)
        self.assertEqual(finished,['lidar','video'])
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(budget.acquire(1000,priority=True),.001)
        self.assertEqual(budget.priority_waiters,0)

    def test_camera_uses_budget_remaining_after_lidar(self):
        sparse=camera_profile(250_000,1,1000)
        dense=camera_profile(250_000,1,3000)
        self.assertEqual(sparse[0],30)
        self.assertGreater(sparse[0],dense[0]);self.assertGreater(sparse[1],dense[1])
        for viewers in (1,2,3,4):
            points=3000//viewers;fps,kbps=camera_profile(250_000,viewers,points)
            self.assertLessEqual(viewers*(points*6*10+kbps*1000/8)+16000,250_000)

    def test_compact_cones_are_bounded_and_stale_results_clear(self):
        row=[-1200,140,-85,30,28,50,21]
        h={'fresh':{'cones':True},'cones':{'items':[row]*80}}
        packed=cone_packet(h,64)
        self.assertEqual(len(packed),3+64*14)
        self.assertEqual(struct.unpack_from('<6hH',packed,3),tuple(row))
        h['fresh']['cones']=False
        self.assertEqual(cone_packet(h,64),b'\x00\x00\x00')
        h['fresh']['cones']=True
        for bad in ([float('nan'),*row[1:]],row[:3]+[-1]+row[4:],row[:-1]+[601]):
            h['cones']['items']=[bad]
            with self.assertRaises(ValueError):cone_packet(h,64)

    def test_point_limit_preserves_far_end(self):
        cloud=b''.join(struct.pack('<hhh',i,0,0) for i in range(4000))
        shown=sample_cloud(cloud,750)
        self.assertEqual(len(shown),750*6)
        self.assertGreater(struct.unpack_from('<h',shown,len(shown)-6)[0],3990)

    def test_lines_are_bounded_atomic_with_cones_and_clear_when_stale(self):
        row=[-200,-200,-110,-2000,-200,-110]
        h={'fresh':{'cones':True},'cones':{'course':{'lines':{k:{'points_cm':row} for k in ('left','right','center','stop')}}}}
        data=line_packet(h)
        self.assertEqual(data[:3],b'L1\x0f')
        self.assertEqual(len(data),51)
        self.assertEqual(struct.unpack_from('<6h',data,3),tuple(row))
        h['fresh']['cones']=False
        self.assertEqual(line_packet(h),b'L1\x00')
        h['fresh']['cones']=True
        h['cones']['course']['lines']['left']['points_cm']=[float('nan')]*6
        with self.assertRaises(ValueError):line_packet(h)


class BrakeWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_state_updates_without_new_cloud_and_freshness_clears_it(self):
        stage=0
        async def snapshot(request):
            cloud=struct.pack('<hhh',-800,100,-80) if request.query.get('cloud')!='1' else b''
            h={'session':'stop-only','mode':'bag','phase':'ready','playing':False,
               'fresh':{'cloud':True,'cones':False,'stop_row':stage==1},
               'versions':{'cloud':1,'camera':0,'cones':0,'stop_row':int(stage>0)},
               'cloud':{'point_count':1},'stop_row':{'state':'candidate','distance_cm':4000,
                    'support_cells':3,'span_cm':240,'points_cm':[-4000,-120,-110,-4000,120,-110]},
               'cloud_bytes':len(cloud),'jpeg_bytes':0}
            header=json.dumps(h).encode()
            return web.Response(body=struct.pack('<I',len(header))+header+cloud)
        backend=web.Application();backend.router.add_get('/snapshot',snapshot)
        async with TestServer(backend) as upstream:
            with patch('dashboard.brake.SOURCE',str(upstream.make_url('')).rstrip('/')):
                app=web.Application();add_routes(app,BrowserTraffic())
                async with TestClient(TestServer(app)) as client:
                    ws=await client.ws_connect('/ws/brake')
                    for expected in (0,1,0):
                        while True:
                            msg=await ws.receive(timeout=3)
                            if msg.type==WSMsgType.BINARY:break
                            self.assertEqual(msg.type,WSMsgType.TEXT)
                            self.assertNotEqual(json.loads(msg.data).get('phase'),'error')
                        self.assertEqual(msg.data[0],1)
                        self.assertEqual(msg.data[17:20],b'S1'+bytes([expected]))
                        self.assertEqual(len(msg.data),17+(21 if expected else 3))
                        await ws.send_str('ack:1');stage+=1
                    await ws.close()

    async def test_paused_cone_completion_and_staleness_update_without_new_cloud(self):
        stage=0
        row=[-800,100,-80,30,24,50,14]
        async def snapshot(request):
            cloud=struct.pack('<hhh',-800,100,-80) if request.query.get('cloud')!='1' else b''
            h={'session':'paused-cones','mode':'bag','phase':'ready','playing':False,
               'fresh':{'cloud':True,'cones':stage==1},
               'versions':{'cloud':1,'camera':0,'cones':int(stage>0)},
               'cloud':{'point_count':1},'cones':{'items':[row] if stage else [],'total':int(stage>0)},
               'cloud_bytes':len(cloud),'jpeg_bytes':0}
            header=json.dumps(h).encode()
            return web.Response(body=struct.pack('<I',len(header))+header+cloud)
        backend=web.Application();backend.router.add_get('/snapshot',snapshot)
        async with TestServer(backend) as upstream:
            with patch('dashboard.brake.SOURCE',str(upstream.make_url('')).rstrip('/')):
                app=web.Application();add_routes(app,BrowserTraffic())
                async with TestClient(TestServer(app)) as client:
                    ws=await client.ws_connect('/ws/brake')
                    for expected in (0,1,0):
                        while True:
                            msg=await ws.receive(timeout=3)
                            if msg.type==WSMsgType.BINARY:break
                            self.assertEqual(msg.type,WSMsgType.TEXT)
                            self.assertNotEqual(json.loads(msg.data).get('phase'),'error')
                        self.assertEqual(msg.data[0],1)
                        self.assertEqual(struct.unpack_from('<I',msg.data,1)[0],1)
                        self.assertEqual(struct.unpack_from('<BH',msg.data,11),(expected,expected))
                        if expected:self.assertEqual(struct.unpack_from('<6hH',msg.data,14),tuple(row))
                        await ws.send_str('ack:1');stage+=1
                    await ws.close()

    async def test_three_sensor_stream_decodes_and_requires_ack(self):
        jpeg = (Path(__file__).parent/'fixtures/camera.jpg').read_bytes()
        sequence = 0
        async def snapshot(request):
            nonlocal sequence
            sequence += 1
            cloud = struct.pack('<hhh', -1000, 100, -50)
            header = {'session':'bag-one', 'mode':'bag', 'phase':'ready','playing':True,
                      'position':sequence*.1,'duration':10,'rate':1,'gps':{'lat':37.2,'lon':126.7,'status':2},
                      'speed_kph':35,'fresh':{'cloud':True,'camera':True,'gps':True},
                      'versions':{'cloud':sequence,'camera':sequence}, 'cloud':{'point_count':1},
                      'cloud_bytes':len(cloud),'jpeg_bytes':len(jpeg)}
            h = json.dumps(header).encode()
            return web.Response(body=struct.pack('<I',len(h))+h+cloud+jpeg)
        backend=web.Application();backend.router.add_get('/snapshot',snapshot)
        async with TestServer(backend) as upstream:
            with patch('dashboard.brake.SOURCE', str(upstream.make_url('')).rstrip('/')):
                app=web.Application();browser=BrowserTraffic();add_routes(app,browser)
                async with TestClient(TestServer(app)) as client:
                    ws=await client.ws_connect('/ws/brake')
                    parts=[];saw_cloud=saw_gps=False;init=None
                    while len(parts)<8:
                        message=await ws.receive(timeout=4)
                        if message.type==WSMsgType.TEXT:
                            data=json.loads(message.data)
                            self.assertFalse(data.get('phase')=='error',data)
                            if data['type']=='status':saw_gps |= data['gps']['lat']==37.2
                            if data['type']=='video-init':init=data
                        elif message.type==WSMsgType.BINARY:
                            if message.data[0]==1:
                                saw_cloud=True;self.assertEqual(struct.unpack_from('<I',message.data,1)[0],1)
                            else:parts.append(message.data[1:])
                            await ws.send_str('ack')
                        else:self.fail(str(message))
                    self.assertTrue(saw_cloud and saw_gps and init)
                    with av.open(io.BytesIO(b''.join(parts))) as stream:
                        self.assertGreater(sum(1 for _ in stream.decode(video=0)),2)
                    self.assertLess(browser.sent, 300_000)
                    await ws.close()

    async def test_proxy_requires_explicit_control_header(self):
        app=web.Application();add_routes(app,BrowserTraffic())
        async with TestClient(TestServer(app)) as client:
            self.assertEqual((await client.post('/api/brake/control',json={'action':'play'})).status,403)

    async def test_paused_single_camera_sample_primes_browser_video(self):
        jpeg = (Path(__file__).parent/'fixtures/camera.jpg').read_bytes()
        async def snapshot(request):
            image = jpeg if request.query.get('camera') != '1' else b''
            h = {'session':'paused', 'mode':'bag', 'phase':'ready', 'playing':False,
                 'fresh':{'camera':True}, 'versions':{'camera':1,'cloud':0},
                 'cloud':{}, 'cloud_bytes':0, 'jpeg_bytes':len(image)}
            header=json.dumps(h).encode()
            return web.Response(body=struct.pack('<I',len(header))+header+image)
        backend=web.Application();backend.router.add_get('/snapshot',snapshot)
        async with TestServer(backend) as upstream:
            with patch('dashboard.brake.SOURCE',str(upstream.make_url('')).rstrip('/')):
                app=web.Application();add_routes(app,BrowserTraffic())
                async with TestClient(TestServer(app)) as client:
                    ws=await client.ws_connect('/ws/brake');parts=[]
                    while len(parts)<3:
                        msg=await ws.receive(timeout=3)
                        if msg.type==WSMsgType.BINARY:
                            self.assertEqual(msg.data[0],2);parts.append(msg.data[1:]);await ws.send_str('ack')
                    with av.open(io.BytesIO(b''.join(parts))) as stream:
                        self.assertGreater(sum(1 for _ in stream.decode(video=0)),0)
                    await ws.close()

    async def test_slow_video_ack_does_not_block_lidar(self):
        jpeg=(Path(__file__).parent/'fixtures/camera.jpg').read_bytes();version=0
        async def snapshot(request):
            nonlocal version
            version+=1;cloud=struct.pack('<hhh',-1000,0,0)
            h={'session':'slow-video','mode':'live','phase':'live','fresh':{'camera':True,'cloud':True},
               'versions':{'camera':version,'cloud':version},'cloud':{'point_count':1},
               'cloud_bytes':6,'jpeg_bytes':len(jpeg)}
            header=json.dumps(h).encode()
            return web.Response(body=struct.pack('<I',len(header))+header+cloud+jpeg)
        backend=web.Application();backend.router.add_get('/snapshot',snapshot)
        async with TestServer(backend) as upstream:
            with patch('dashboard.brake.SOURCE',str(upstream.make_url('')).rstrip('/')):
                app=web.Application();add_routes(app,BrowserTraffic())
                async with TestClient(TestServer(app)) as client:
                    ws=await client.ws_connect('/ws/brake');epoch=0;clouds=videos=0;started=time.monotonic()
                    while time.monotonic()-started<1.7:
                        msg=await ws.receive(timeout=3)
                        if msg.type==WSMsgType.TEXT:
                            h=json.loads(msg.data)
                            if h['type']=='reset':epoch=h['render_epoch']
                        elif msg.type==WSMsgType.BINARY:
                            if msg.data[0]==1:
                                clouds+=1;await ws.send_str(f'ack:1:{epoch}')
                            else:videos+=1  # Deliberately withhold video ACKs.
                        else:self.fail(str(msg))
                    self.assertGreaterEqual(clouds,12)
                    self.assertEqual(videos,3)
                    await ws.close()

    def test_rejects_malformed_point_packet(self):
        for cloud_bytes in (-1, 5, 24006):
            h=json.dumps({'cloud_bytes':cloud_bytes,'jpeg_bytes':0}).encode()
            with self.assertRaises(ValueError):unpack(struct.pack('<I',len(h))+h)
