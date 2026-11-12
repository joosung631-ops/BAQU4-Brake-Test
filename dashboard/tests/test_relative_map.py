import unittest
from aiohttp.test_utils import TestClient, TestServer
from dashboard.__main__ import create_app


class RelativeMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_lidar_map_routes_are_disabled(self):
        async with TestClient(TestServer(create_app())) as client:
            for route in ['/api/relative-map/summary', '/api/relative-map/points',
                          '/api/ros/lidar-map/state', '/api/relative-map/../../config.yaml']:
                self.assertEqual((await client.get(route)).status, 404, route)
