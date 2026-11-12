import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from aiohttp.test_utils import TestClient, TestServer
    from dashboard.__main__ import create_app
    from dashboard.browser_traffic import BROWSER_TRAFFIC
except ModuleNotFoundError:
    TestClient = None


@unittest.skipIf(TestClient is None, 'aiohttp is available in the dashboard container')
class BrowserTrafficTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_stats_commands_count_but_internal_reports_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.yaml'
            path.write_text('groups: []')
            with patch.dict(os.environ, {'DASHBOARD_TOPIC_CONFIG': str(path)}):
                app = create_app()
            meter = app[BROWSER_TRAFFIC]
            async with TestClient(TestServer(app)) as client:
                self.assertEqual(meter.sent + meter.received, 0)
                response = await client.post('/api/ros/topics', json={'topics': [
                    {'name': '/sensor', 'hz': 10, 'age': 0}]})
                self.assertEqual(response.status, 204)
                await client.get('/api/camera/demand')
                self.assertEqual(meter.sent + meter.received, 0)
                response = await client.get('/')
                page = await response.read()
                self.assertEqual(meter.sent, len(page))
                async with client.ws_connect('/ws/traffic') as ws:
                    first = await ws.receive_str(timeout=2)
                    self.assertEqual(meter.sent, len(page) + len(first.encode('utf-8')))
                    command = '{"mode":"live"}'
                    await ws.send_str(command)
                    second = await ws.receive_str(timeout=2)
                    self.assertEqual(meter.received, len(command.encode('utf-8')))
                    self.assertEqual(meter.sent, len(page) + len(first.encode('utf-8')) + len(second.encode('utf-8')))

    # 이전: test_local_view_does_not_count_as_internet
    async def test_legacy_local_flag_is_also_counted_as_remote(self):
        app = create_app()
        meter = app[BROWSER_TRAFFIC]
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/?internet=0')
            # 이전에는 internet=0을 전파했지만 현재는 원격으로 고정한다.
            self.assertIn('src="/gps.js?internet=1"', await response.text())
            await client.get('/gps.js?internet=0')
            async with client.ws_connect('/ws/traffic?internet=0') as ws:
                await ws.receive_json(timeout=2)
                await ws.send_str('{"mode":"bag"}')
                await ws.receive_json(timeout=2)
            self.assertGreater(meter.sent, 0)
            self.assertGreater(meter.received, 0)
            # 이전: self.assertEqual(meter.internet_sent + meter.internet_received, 0)
            self.assertEqual(meter.internet_sent, meter.sent)
            self.assertEqual(meter.internet_received, meter.received)

    async def test_remote_default_counts_http_gps_and_websocket(self):
        app = create_app()
        meter = app[BROWSER_TRAFFIC]
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/')
            self.assertIn('src="/gps.js?internet=1"', await response.text())
            await client.get('/gps.js?internet=1')
            self.assertEqual(meter.internet_sent, meter.sent)
            async with client.ws_connect('/ws/gps?internet=1') as ws:
                await ws.receive_json(timeout=2)
            self.assertEqual(meter.internet_sent, meter.sent)
            before = meter.internet_sent
            async with client.ws_connect('/ws/gps?internet=0') as ws:
                await ws.receive_json(timeout=2)
            # 이전에는 internet=0 연결을 제외했다. 현재는 전부 포함한다.
            self.assertGreater(meter.internet_sent, before)
            self.assertEqual(meter.sent, meter.internet_sent)

    async def test_remote_binary_and_text_uploads_are_counted(self):
        from aiohttp import web
        from dashboard.browser_traffic import ViewerWebSocket
        from dashboard.traffic import BrowserTraffic
        meter = BrowserTraffic()
        async def echo(request):
            ws = ViewerWebSocket(meter)
            await ws.prepare(request)
            await ws.receive()
            await ws.send_bytes(b'frame')
            await ws.receive()
            await ws.send_str('ack')
            await ws.close()
            return ws
        app = web.Application()
        app.router.add_get('/echo', echo)
        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect('/echo?internet=1') as ws:
                await ws.send_bytes(b'12')
                self.assertEqual((await ws.receive()).data, b'frame')
                await ws.send_str('xyz')
                self.assertEqual((await ws.receive()).data, 'ack')
            self.assertEqual(meter.internet_sent, 8)
            self.assertEqual(meter.internet_received, 5)
