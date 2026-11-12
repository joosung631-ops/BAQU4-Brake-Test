import unittest
from dashboard.gps_live import GPSLive
from dashboard.traffic import BrowserTraffic
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


def point(seq, t=1789884220, quality=4):
    return {'seq':seq,'t':t,'lat':37.2,'lon':126.7,'status':2,'quality':quality}


class GPSTests(unittest.TestCase):
    def test_accumulate_across_bags_and_loops_without_duplicates(self):
        gps=GPSLive(None)
        gps.update({'session':'a','points':[point(1),point(2)]},now=0)
        stream=gps.stream_id
        gps.update({'session':'a','points':[point(1),point(2)]},now=1)
        self.assertEqual(len(gps.points),2)
        gps.update({'session':'b','points':[point(1,quality=1)]},now=2)
        packet=gps.packet(stream,2,now=3)
        self.assertFalse(packet['reset'])
        self.assertEqual([p['seq'] for p in packet['points']],[3])
        self.assertEqual(packet['points'][0]['quality'],1)
        self.assertTrue(packet['active'])
        self.assertFalse(gps.packet(stream,3,now=6)['active'])

    def test_clear_preserves_source_watermark_and_origin_restarts(self):
        gps=GPSLive(None)
        gps.update({'session':'a','points':[point(1),point(2)]})
        previous=gps.stream_id
        gps.clear()
        gps.update({'session':'a','points':[point(1),point(2)]})
        self.assertEqual(gps.points,[])
        gps.update({'session':'a','points':[point(2),point(3)]})
        packet=gps.packet(previous,2)
        self.assertTrue(packet['reset'])
        self.assertEqual(len(packet['points']),1)
        self.assertEqual(packet['seq'],1)

    def test_invalid_report_is_atomic(self):
        gps=GPSLive(None);gps.update({'session':'a','points':[point(1)]})
        for bad in [point(2,-1),{**point(2),'lat':float('nan')},{**point(2),'status':-1},{**point(2),'quality':99}]:
            with self.assertRaises(ValueError):gps.update({'session':'b','points':[point(1),bad]})
            self.assertEqual(gps.session,'a');self.assertEqual(len(gps.points),1)

    def test_history_not_evicted_and_reconnect_is_chunked(self):
        gps=GPSLive(None)
        for seq in range(1,10005):gps.update({'session':'a','points':[point(seq)]})
        self.assertEqual(len(gps.points),10004)
        first=gps.packet(None,0)
        self.assertEqual(len(first['points']),512)
        second=gps.packet(first['session'],first['seq'])
        self.assertEqual(second['points'][0]['seq'],513)
        self.assertFalse(second['reset'])


class GPSWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_clear_and_reconnect(self):
        gps=GPSLive(None);app=web.Application();browser=BrowserTraffic();gps.add_routes(app,browser)
        async with TestClient(TestServer(app)) as client:
            ws=await client.ws_connect('/ws/gps');await ws.receive_json()
            response=await client.post('/api/ros/gps',json={'session':'a','points':[point(1)]})
            self.assertEqual(response.status,204)
            packet=await ws.receive_json(timeout=2)
            self.assertEqual(len(packet['points']),1)
            self.assertEqual((await ws.receive_json(timeout=2))['points'],[])
            self.assertEqual((await client.post('/api/gps/clear')).status,403)
            self.assertEqual((await client.post('/api/gps/clear',headers={'X-Dashboard-Control':'1'})).status,204)
            packet=await ws.receive_json(timeout=2)
            self.assertTrue(packet['reset']);self.assertEqual(packet['points'],[])
            await ws.close()
            ws=await client.ws_connect('/ws/gps')
            self.assertEqual((await ws.receive_json(timeout=2))['points'],[])
            await ws.close()
