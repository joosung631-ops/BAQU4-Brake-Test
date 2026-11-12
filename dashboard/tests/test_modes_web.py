"""Exercise per-browser mode switching through the actual HTTP/WebSocket API."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from aiohttp.test_utils import TestClient, TestServer
    from dashboard.__main__ import create_app
except ModuleNotFoundError:
    TestClient = None


CONFIG = '''
default_mode: live
modes:
  live:
    label: 실시간
    groups:
      - name: 카메라
        topics: [/raw, /compressed]
  bag:
    label: ROS bag
    groups:
      - name: 카메라
        topics: [/compressed]
'''


@unittest.skipIf(TestClient is None, "aiohttp is available in the dashboard container")
class ModeWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_switch_isolated_reconnect_and_config_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(CONFIG)
            with patch.dict(os.environ, {"DASHBOARD_TOPIC_CONFIG": str(path)}):
                async with TestClient(TestServer(create_app())) as client:
                    response = await client.post('/api/ros/topics', json={"topics": [
                        {"name": "/compressed", "hz": 30, "age": 0}]})
                    self.assertEqual(response.status, 204)
                    live = await client.ws_connect('/ws/traffic')
                    bag = await client.ws_connect('/ws/traffic?mode=bag')

                    async def receive(ws, mode, status=None):
                        for _ in range(5):
                            data = await ws.receive_json(timeout=3)
                            if data['topic_mode'] == mode and (
                                    status is None or data['topic_groups'][0]['status'] == status):
                                return data
                        self.fail('Expected mode/status not received')

                    data = await receive(bag, 'bag', 'ok')
                    self.assertEqual([m['id'] for m in data['topic_modes']], ['live', 'bag'])
                    self.assertEqual(len(data['topic_groups'][0]['topics']), 1)
                    await receive(live, 'live', 'error')
                    await live.send_json({'mode': 'bag'})
                    await receive(live, 'bag')
                    await live.send_json({'mode': 'live'})
                    await receive(live, 'live', 'error')
                    await receive(bag, 'bag')
                    await live.send_str('invalid json')
                    await live.send_json({'mode': ['bag']})
                    await receive(live, 'live')
                    await bag.close()
                    bag = await client.ws_connect('/ws/traffic?mode=bag')
                    await receive(bag, 'bag')
                    # Removing a selected mode falls back without closing clients.
                    path.write_text('modes: {live: {label: 실시간, groups: []}}')
                    data = await receive(bag, 'live')
                    self.assertEqual(data['topic_groups'][0]['name'], '예외')
                    await live.close()
                    await bag.close()
