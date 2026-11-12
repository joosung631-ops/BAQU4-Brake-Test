import asyncio
import json
import struct
import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from dashboard.lidar_live import LidarLive, encode, decode, VIEW_POINTS
from dashboard.traffic import BrowserTraffic


def report(session='a',start=0,count=2,path_start=0,path_count=1):
    h={'session':session,'point_start':start,'point_end':start+count,'path_start':path_start,'point_count':count,'path_count':path_count,
       'status':{'scans':5,'age_s':0,'processing_ms':20}}
    return encode(h,b''.join(struct.pack('<Ifff',i,1,2,3) for i in range(start,start+count)),struct.pack('<fff',4,5,6)*path_count)


class LidarStoreTests(unittest.TestCase):
    def test_delta_duplicate_retry_restart_and_reset(self):
        store=LidarLive()
        self.assertTrue(store.update(report()))
        self.assertFalse(store.update(report()))
        self.assertEqual(store.cursor(),{'session':'a','points':2,'revision':2,'path':1})
        self.assertTrue(store.update(report(start=2,count=1,path_start=1)))
        h,body=store.packet('a',2,1)
        self.assertFalse(h['reset']);self.assertEqual(h['point_count'],1)
        self.assertEqual(len(decode(body)[1]),28)
        restarted=LidarLive()
        self.assertFalse(restarted.update(report(start=2)))
        self.assertTrue(restarted.update(report()))
        self.assertTrue(store.update(report(session='b',count=1)))
        self.assertEqual(store.cursor()['points'],1)
        self.assertTrue(store.packet('a',3,2)[0]['reset'])

    def test_replacements_coalesce_and_reconnect_restores_latest(self):
        store=LidarLive();store.update(report())
        for start,x in ((2,10),(3,20)):
            h,_=decode(report(start=start,count=1,path_start=1,path_count=0))
            self.assertTrue(store.update(encode(h,struct.pack('<Ifff',0,x,2,3))))
        self.assertEqual(len(store.points),2)
        h,packet=store.packet('a',2,1)
        self.assertEqual(h['point_count'],1);self.assertEqual(h['point_end'],4)
        self.assertEqual(struct.unpack('<Ifff',decode(packet)[1]),(0,20,2,3))
        h,packet=store.packet(None,0,0)
        self.assertTrue(h['reset']);self.assertEqual(h['point_count'],2)
        records=list(struct.iter_unpack('<Ifff',decode(packet)[1][:32]))
        self.assertEqual({r[0]:r[1] for r in records},{0:20,1:1})
        # An update after a batch was sent remains available after its acknowledgement.
        h,_=decode(report(start=4,count=1,path_start=1,path_count=0))
        store.update(encode(h,struct.pack('<Ifff',0,30,2,3)))
        self.assertEqual(store.packet('a',4,1)[0]['point_count'],1)

    def test_validation_is_atomic_and_finite(self):
        store=LidarLive();store.update(report())
        h,_=decode(report(session='b',count=1,path_count=0))
        for body in (b'',struct.pack('<Ifff',0,float('nan'),0,0)):
            with self.assertRaises(ValueError):store.update(encode(h,body))
            self.assertEqual(store.session,'a')
        h['point_end']=0
        with self.assertRaises(ValueError):store.update(encode(h,struct.pack('<Ifff',0,0,0,0)))

    def test_restore_chunks_are_capped_and_idle_has_no_cloud(self):
        store=LidarLive();store.update(report(count=VIEW_POINTS+5))
        h,_=store.packet(None,0,0)
        self.assertEqual(h['point_count'],VIEW_POINTS)
        h,_=store.packet('a',VIEW_POINTS,1)
        self.assertEqual(h['point_count'],5)
        h,packet=store.packet('a',VIEW_POINTS+5,1)
        self.assertEqual(h['point_count'],0);self.assertEqual(h['path_count'],0)
        self.assertEqual(decode(packet)[1],b'')


class LidarWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_ack_gates_deltas_reconnect_and_internal_traffic(self):
        store=LidarLive();meter=BrowserTraffic();app=web.Application();store.add_routes(app,meter)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/ros/lidar-map',data=report(count=VIEW_POINTS+5))
            self.assertEqual(response.status,200);self.assertEqual(meter.sent,0)
            response=await client.post('/api/ros/lidar-map',data=report(count=VIEW_POINTS+5))
            self.assertEqual(response.status,409)
            ws=await client.ws_connect('/ws/lidar-map')
            first=await ws.receive_bytes();h,body=decode(first)
            self.assertEqual(h['point_count'],VIEW_POINTS)
            pending=asyncio.create_task(ws.receive_bytes())
            await asyncio.sleep(1.1)
            self.assertFalse(pending.done(),'Must wait for acknowledgement before sending another batch')
            await ws.send_json({'session':'a','points':VIEW_POINTS,'path':1})
            second=await asyncio.wait_for(pending,2);h,_=decode(second)
            self.assertEqual(h['point_start'],VIEW_POINTS);self.assertEqual(h['point_count'],5)
            self.assertEqual(meter.sent,len(first)+len(second))
            await ws.close();sent=meter.sent
            await client.post('/api/ros/lidar-map',data=report(start=VIEW_POINTS+5,count=1,path_start=1))
            await asyncio.sleep(.05);self.assertEqual(meter.sent,sent)
            ws=await client.ws_connect('/ws/lidar-map')
            h,_=decode(await ws.receive_bytes());self.assertTrue(h['reset']);self.assertEqual(h['point_start'],0)
            await ws.close()
