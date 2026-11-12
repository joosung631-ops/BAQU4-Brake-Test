import asyncio
from pathlib import Path
import unittest

from aiohttp import ClientSession, web

from dashboard.http_server import DashboardRunner


class ConnectionDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = web.Application()

        async def index(request):
            return web.Response(text='ok')

        async def websocket(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for message in ws:
                await ws.send_str(message.data)
            return ws

        async def slow(request):
            await asyncio.sleep(.25)
            return web.Response(text='finished')

        self.app.router.add_get('/', index)
        self.app.router.add_get('/ws', websocket)
        self.app.router.add_get('/slow', slow)
        self.runner = DashboardRunner(self.app, first_request_timeout=.15,
                                      keepalive_timeout=.2, shutdown_timeout=1)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await self.site.start()
        self.port = self.site.port
        self.connections = []

    async def asyncTearDown(self):
        for reader, writer in self.connections:
            writer.close()
            await writer.wait_closed()
        await self.runner.cleanup()
        self.assertFalse(self.runner.deadline.pending)

    async def connect(self):
        connection = await asyncio.open_connection('127.0.0.1', self.port)
        self.connections.append(connection)
        return connection

    async def test_empty_and_incomplete_header_connections_expire(self):
        empty, _ = await self.connect()
        partial, writer = await self.connect()
        writer.write(b'GET / HTTP/1.1\r\nHost: tunnel')
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(empty.read(), 1), b'')
        self.assertEqual(await asyncio.wait_for(partial.read(), 1), b'')
        self.assertFalse(self.runner.deadline.pending)

    async def test_slow_route_and_websocket_survive_first_request_deadline(self):
        async with ClientSession() as client:
            async with client.get(f'http://127.0.0.1:{self.port}/slow') as response:
                self.assertEqual(await response.text(), 'finished')
            async with client.ws_connect(f'http://127.0.0.1:{self.port}/ws') as ws:
                await asyncio.sleep(.35)
                await ws.send_str('still connected')
                self.assertEqual((await ws.receive(timeout=1)).data, 'still connected')

    async def test_idle_keepalive_is_closed_after_successful_response(self):
        reader, writer = await self.connect()
        writer.write(b'GET / HTTP/1.1\r\nHost: test\r\n\r\n')
        await writer.drain()
        headers = await reader.readuntil(b'\r\n\r\n')
        self.assertIn(b'200 OK', headers)
        self.assertEqual(await reader.readexactly(2), b'ok')
        self.assertEqual(await asyncio.wait_for(reader.read(), 1), b'')

    async def test_repeated_tunnel_connections_return_descriptors_to_baseline(self):
        baseline = len(list(Path('/proc/self/fd').iterdir()))
        for _ in range(3):
            batch = await asyncio.gather(*(self.connect() for _ in range(64)))
            for reader, writer in batch:
                self.assertEqual(await asyncio.wait_for(reader.read(), 1), b'')
                writer.close()
                await writer.wait_closed()
            await asyncio.sleep(.02)
            self.assertLessEqual(len(list(Path('/proc/self/fd').iterdir())), baseline+3)
            self.assertFalse(self.runner.deadline.pending)
