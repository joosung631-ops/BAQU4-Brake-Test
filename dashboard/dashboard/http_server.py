"""Bound empty tunnel connections before they consume every server descriptor."""
import asyncio
import signal

from aiohttp import web


class FirstRequestDeadline:
    def __init__(self, timeout=10):
        self.timeout = timeout
        self.pending = {}

    def accepted(self, protocol):
        self.pending[protocol] = asyncio.get_running_loop().call_later(
            self.timeout, self.expire, protocol)

    def expire(self, protocol):
        self.pending.pop(protocol, None)
        # aiohttp 3.14.3 increments this only after parsing complete headers.
        # Its keepalive timeout starts after a response, leaving the first
        # request unbounded. Do not interrupt a parsed request or WebSocket.
        if protocol._request_count == 0:
            protocol.force_close()

    @web.middleware
    async def request_started(self, request, handler):
        timer = self.pending.pop(request.protocol, None)
        if timer is not None:
            timer.cancel()
        return await handler(request)

    def close(self):
        for timer in self.pending.values():
            timer.cancel()
        self.pending.clear()


class DeadlineServer:
    def __init__(self, server, deadline):
        self.server, self.deadline = server, deadline

    def __call__(self):
        protocol = self.server()
        self.deadline.accepted(protocol)
        return protocol

    @property
    def connections(self):
        return self.server.connections

    def pre_shutdown(self):
        self.deadline.close()
        self.server.pre_shutdown()

    async def shutdown(self, timeout=None):
        self.deadline.close()
        await self.server.shutdown(timeout)


class DashboardRunner(web.AppRunner):
    def __init__(self, app, *, first_request_timeout=10, **kwargs):
        self.deadline = FirstRequestDeadline(first_request_timeout)
        app.middlewares.insert(0, self.deadline.request_started)
        # Reuse working HTTP connections, but promptly retire idle ones.
        kwargs.setdefault('keepalive_timeout', 15)
        super().__init__(app, **kwargs)

    async def _make_server(self):
        return DeadlineServer(await super()._make_server(), self.deadline)


async def serve(app, host, port):
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = (signal.SIGTERM, signal.SIGINT)
    for signum in signals:
        loop.add_signal_handler(signum, stopped.set)
    runner = DashboardRunner(app, shutdown_timeout=5)
    try:
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        print(f'======== Running on http://{host}:{port} ========', flush=True)
        await stopped.wait()
    finally:
        await runner.cleanup()
        for signum in signals:
            loop.remove_signal_handler(signum)
