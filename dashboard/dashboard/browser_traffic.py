"""Count viewer payloads only; no Docker, ROS, HTTP/TCP or tunnel byte estimates."""

from aiohttp import web, WSMsgType

from .traffic import BrowserTraffic
from .bandwidth import ViewerBudget


BROWSER_TRAFFIC = web.AppKey("browser_traffic", BrowserTraffic)
VIEWER_PATHS = {"/", "/ws/traffic", "/ws/camera", "/ws/gps", "/ws/lidar-map", "/gps.js", "/api/gps/tracks", "/relative-map.js", "/relative-surface.js", "/api/relative-map/summary", "/api/relative-map/points"}
VIEWER_PATHS.update({'/ws/brake', '/brake.js', '/brake.css', '/api/brake/bags', '/api/brake/control'})


@web.middleware
async def count_page_traffic(request, handler):
    if request.path not in VIEWER_PATHS:
        return await handler(request)
    try:
        response = await handler(request)
    except web.HTTPException as error:
        response = error
    if isinstance(response, web.Response) and request.method != "HEAD":
        if isinstance(response.body, bytes):
            if hasattr(request.app[BROWSER_TRAFFIC], 'budget'):
                await request.app[BROWSER_TRAFFIC].budget.acquire(len(response.body))
            request.app[BROWSER_TRAFFIC].sent += len(response.body)
            # 이전 접속 분류: if request.query.get("internet", "1") == "1":
            request.app[BROWSER_TRAFFIC].internet_sent += len(response.body)
    return response


class ViewerWebSocket(web.WebSocketResponse):
    def __init__(self, meter, **kwargs):
        super().__init__(**kwargs)
        self.meter = meter
        self.internet = False

    async def prepare(self, request):
        # 이전 URL의 internet=0도 무시하고 외부 접속으로 고정한다.
        # 이전: self.internet = request.query.get("internet", "1") == "1"
        self.internet = True  # 사용자 지정: 모든 접속을 외부 접속으로 계산.
        return await super().prepare(request)

    async def send_str(self, data, compress=None):
        if not hasattr(self.meter, 'budget'): self.meter.budget = ViewerBudget()
        await self.meter.budget.acquire(len(data.encode('utf-8')))
        await super().send_str(data, compress=compress)
        self.meter.sent += len(data.encode("utf-8"))
        if self.internet:
            self.meter.internet_sent += len(data.encode("utf-8"))

    async def send_bytes(self, data, compress=None, *, priority=False):
        if not hasattr(self.meter, 'budget'): self.meter.budget = ViewerBudget()
        await self.meter.budget.acquire(len(data), priority=priority)
        await super().send_bytes(data, compress=compress)
        self.meter.sent += len(data)
        if self.internet:
            self.meter.internet_sent += len(data)

    async def receive(self, timeout=None):
        message = await super().receive(timeout=timeout)
        if message.type == WSMsgType.TEXT:
            self.meter.received += len(message.data.encode("utf-8"))
            if self.internet:
                self.meter.internet_received += len(message.data.encode("utf-8"))
        elif message.type == WSMsgType.BINARY:
            self.meter.received += len(message.data)
            if self.internet:
                self.meter.internet_received += len(message.data)
        return message
