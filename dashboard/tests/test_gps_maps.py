import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from dashboard.gps_maps import add_routes


class GPSMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_load_refresh_and_restrict_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'gps-map.json').write_text('{"point_count":534}')
            (root/'main.py').write_text('private code')
            (root/'escape.json').symlink_to(root/'main.py')
            with patch.dict(os.environ, {'DASHBOARD_GPS_MAP_DIR':folder}):
                app=web.Application();add_routes(app)
            async with TestClient(TestServer(app)) as client:
                response=await client.get('/api/gps/maps')
                self.assertEqual(await response.json(), {'maps':['gps-map.json']})
                response=await client.get('/api/gps/maps/gps-map.json')
                self.assertEqual((await response.json())['point_count'],534)
                for name in ['main.py','escape.json','missing.json','..%2Fmain.py']:
                    response=await client.get('/api/gps/maps/'+name)
                    self.assertEqual(response.status,404)
                (root/'new.json').write_text('{}')
                response=await client.get('/api/gps/maps')
                self.assertEqual((await response.json())['maps'],['gps-map.json','new.json'])

    async def test_raw_camera_routes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);frames=root/'test'/'frames';frames.mkdir(parents=True)
            (root/'test'/'raw.json').write_text('{"format":"gps-test-raw"}')
            name='a'*64+'.jpg';(frames/name).write_bytes(b'\xff\xd8test\xff\xd9')
            (frames/('b'*64+'.jpg')).symlink_to(frames/name)
            with patch.dict(os.environ, {'DASHBOARD_GPS_MAP_DIR':folder}):
                app=web.Application();add_routes(app)
            async with TestClient(TestServer(app)) as client:
                response=await client.get('/api/gps/test')
                self.assertEqual((await response.json())['format'],'gps-test-raw')
                response=await client.get('/api/gps/test/frames/'+name)
                self.assertEqual(response.status,200)
                self.assertEqual(await response.read(),b'\xff\xd8test\xff\xd9')
                for invalid in ['raw.json','b'*64+'.jpg','c'*64+'.jpg','..%2Fraw.json']:
                    response=await client.get('/api/gps/test/frames/'+invalid)
                    self.assertEqual(response.status,404)
                response=await client.get('/api/gps/maps')
                self.assertEqual((await response.json())['maps'],[])
