import asyncio
import io
from pathlib import Path
import tempfile
import time
import unittest
import av
import numpy as np
from aiohttp import web, WSMsgType
from aiohttp.test_utils import TestClient, TestServer
from dashboard.camera import CameraHub
from dashboard.topic_groups import TopicGroups


def jpeg():
    return (Path(__file__).parent/'fixtures/camera.jpg').read_bytes()


class CameraTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        path=Path(self.directory.name)/'config.yaml'
        path.write_text('modes: {live: {groups: [{name: camera, topics: [{name: /raw, image: true}]}]}}')
        groups=TopicGroups(path);groups.reload();self.hub=CameraHub(groups)
        app=web.Application(client_max_size=self.hub.MAX_FRAME_BYTES);self.hub.add_routes(app)
        self.client=TestClient(TestServer(app));await self.client.start_server();self.addAsyncCleanup(self.client.close)
        self.jpeg=jpeg()

    async def demand(self):return (await (await self.client.get('/api/camera/demand')).json())['streams']

    async def upload(self,token):
        return await self.client.post('/api/camera/frame?topic=/raw&token='+token,
            data=self.jpeg,headers={'Content-Type':'image/jpeg'})

    async def test_fps_validation_and_independent_profiles(self):
        for fps in ('0','1','6','29','31','15.0','bad'):
            self.assertEqual((await self.client.get('/ws/camera?mode=live&topic=/raw&fps='+fps)).status,400)
        for fps in (5,10,15,20,25,30):
            ws=await self.client.ws_connect(f'/ws/camera?mode=live&topic=/raw&fps={fps}')
            self.assertEqual((await self.demand())[0]['fps'],fps);await ws.close()
        self.assertEqual(await self.demand(),[])

    async def test_real_fmp4_decode_shared_source_and_release(self):
        slow=await self.client.ws_connect('/ws/camera?mode=live&topic=/raw&fps=5')
        fast=await self.client.ws_connect('/ws/camera?mode=live&topic=/raw&fps=30')
        demand=(await self.demand())[0];self.assertEqual(demand['fps'],30)
        self.assertEqual((await self.upload('wrong')).status,409)
        parts=[];initial=[]
        async def receive(ws):
            async for msg in ws:
                if msg.type==WSMsgType.BINARY:
                    if ws is fast:parts.append(msg.data)
                    await ws.send_str('ack')
                elif msg.type==WSMsgType.TEXT:
                    import json
                    data=json.loads(msg.data)
                    if data.get('type')=='init':initial.append(data)
                    self.assertNotEqual(data.get('type'),'error',data)
        tasks=[asyncio.create_task(receive(ws)) for ws in (slow,fast)]
        for _ in range(32):await self.upload(demand['token']);await asyncio.sleep(1/30)
        self.assertEqual(sorted(x['fps'] for x in initial),[5,30])
        self.assertEqual(sorted(x['bitrate_kbps'] for x in initial),[600,1800])
        self.assertTrue(parts[0][4:8]==b'ftyp')
        with av.open(io.BytesIO(b''.join(parts))) as video:
            self.assertGreater(sum(1 for _ in video.decode(video=0)),15)
        await fast.close();self.assertEqual((await self.demand())[0]['fps'],5)
        await slow.close();await asyncio.gather(*tasks);self.assertEqual(await self.demand(),[])

    async def test_ack_timeout_releases_camera_and_bad_timestamp(self):
        self.hub.ACK_TIMEOUT=.25
        ws=await self.client.ws_connect('/ws/camera?mode=live&topic=/raw&fps=15')
        token=(await self.demand())[0]['token']
        response=await self.client.post('/api/camera/frame?topic=/raw&token='+token,data=self.jpeg,
            headers={'Content-Type':'image/jpeg','X-Capture-Monotonic':'nan'})
        self.assertEqual(response.status,400)
        await self.upload(token)
        for _ in range(6):
            message=await ws.receive(timeout=1)
            if message.type==WSMsgType.CLOSE:break
        self.assertTrue(ws.closed);await ws.close();self.assertEqual(await self.demand(),[])

    async def test_live_and_bag_viewers_use_distinct_sources_and_tokens(self):
        self.hub.groups.modes['bag'] = self.hub.groups.modes['live']
        live = await self.client.ws_connect('/ws/camera?mode=live&topic=/raw&fps=15')
        bag = await self.client.ws_connect('/ws/camera?mode=bag&topic=/raw&fps=15')
        demand = {row['topic']: row for row in await self.demand()}
        self.assertEqual(set(demand), {'/raw', '/dashboard/bag/raw'})
        self.assertNotEqual(demand['/raw']['token'], demand['/dashboard/bag/raw']['token'])
        # Replay token cannot upload into the live source or share its latest frame.
        self.assertEqual((await self.upload(demand['/dashboard/bag/raw']['token'])).status, 409)
        self.assertEqual((await self.upload(demand['/raw']['token'])).status, 204)
        self.assertEqual(self.hub.streams['/raw'].version, 1)
        self.assertIsNone(self.hub.streams['/dashboard/bag/raw'].jpeg)
        response = await self.client.post('/api/camera/frame?topic=/dashboard/bag/raw&token=' +
            demand['/dashboard/bag/raw']['token'], data=self.jpeg,
            headers={'Content-Type': 'image/jpeg'})
        self.assertEqual(response.status, 204)
        await live.close(); await bag.close()
        self.assertEqual(await self.demand(), [])

    async def test_bag_without_replay_does_not_request_live_camera(self):
        self.hub.groups.modes['bag'] = self.hub.groups.modes['live']
        bag = await self.client.ws_connect('/ws/camera?mode=bag&topic=/raw&fps=15')
        demand = await self.demand()
        self.assertEqual([row['topic'] for row in demand], ['/dashboard/bag/raw'])
        self.assertEqual((await self.upload(demand[0]['token'])).status, 409)
        self.assertIsNone(self.hub.streams['/dashboard/bag/raw'].jpeg)
        await bag.close()
