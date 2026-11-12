import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('extract_gps', Path(__file__).parents[1]/'tools'/'extract_gps.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GPSGeometryTests(unittest.TestCase):
    def test_cdr_alignment_and_both_byte_orders(self):
        for order, identifier in [('<', b'\x00\x01'), ('>', b'\x00\x00')]:
            payload = bytearray()
            def put(fmt, alignment, *values):
                payload.extend(b'\0' * (-len(payload) % alignment))
                payload.extend(struct.pack(order+fmt, *values))
            put('iI',4,100,500000000)
            put('I',4,5)
            payload.extend(b'gnss\0')
            put('b',1,2)
            put('H',2,1)
            put('ddd',8,37.2,126.7,30)
            self.assertEqual(module.decode_fix(identifier+b'\0\0'+payload), (100.5,2,37.2,126.7,30))

    def test_common_origin_and_axis_directions(self):
        origin = (37.2,126.7,30)
        self.assertEqual(module.enu(37.2,126.7,origin),(0,0))
        east,north = module.enu(37.2,126.701,origin)
        self.assertGreater(east,80)
        self.assertLess(abs(north),.01)
        east,north = module.enu(37.201,126.7,origin)
        self.assertGreater(north,110)
        self.assertLess(abs(east),.01)

try:
    from aiohttp.test_utils import TestClient, TestServer
    from dashboard.__main__ import create_app
    from dashboard.browser_traffic import BROWSER_TRAFFIC
except ModuleNotFoundError:
    TestClient = None


@unittest.skipIf(TestClient is None, 'aiohttp required')
class GPSWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_tracks_and_script_count_as_viewer_traffic(self):
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            before = app[BROWSER_TRAFFIC].sent
            response = await client.get('/api/gps/tracks')
            self.assertEqual(response.status,200)
            raw = await response.read()
            data = await response.json()
            self.assertEqual(data['date'],'2026-09-20')
            self.assertEqual(len(data['bags']),9)
            self.assertEqual(data['bags'][0]['points'],[])
            self.assertTrue(all(b['id'].startswith('2026-09-20_') for b in data['bags']))
            script = await client.get('/gps.js')
            self.assertEqual(script.status,200)
            self.assertEqual(app[BROWSER_TRAFFIC].sent-before,len(raw)+len(await script.read()))
