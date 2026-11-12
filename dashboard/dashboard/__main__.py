import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path

from aiohttp import web

from .traffic import BrowserTraffic, TrafficMonitor
from .browser_traffic import BROWSER_TRAFFIC, ViewerWebSocket, count_page_traffic
from .topics import TopicStore
from .topic_groups import TopicGroups
from .camera import CameraHub
from .gps_live import GPSLive
from .monitor_1021 import add_routes as add_monitor_1021_routes
from .gps_maps import add_routes as add_gps_map_routes
from .gps_project import add_routes as add_gps_project_routes
from .gps_workflow import add_routes as add_gps_workflow_routes
from .gps_review import add_routes as add_gps_review_routes
from .gps_sources import add_routes as add_gps_source_routes
from .bag_control import add_routes as add_bag_routes
from .http_server import serve
from .brake import add_routes as add_brake_routes
from .map_position import add_routes as add_map_position_routes
from .map_compare import add_routes as add_map_compare_routes


def create_app() -> web.Application:
    page = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
    browser = BrowserTraffic()
    # 이전: monitor = TrafficMonitor(uplink=os.environ.get("DASHBOARD_UPLINK_INTERFACE", ""), browser=browser)
    monitor = TrafficMonitor(uplink=os.environ.get("DASHBOARD_UPLINK_INTERFACE", ""), browser=browser,
                             internet_path=os.environ.get("DASHBOARD_INTERNET_COUNTER"))
    snapshots = {}
    sockets = set()
    topics = TopicStore()
    groups = TopicGroups()
    camera = CameraHub(groups, browser=browser)

    def sample():
        nonlocal snapshots
        groups.reload()
        monitor.set_smoothing_samples(groups.traffic["smoothing_samples"])
        data = monitor.sample()
        received = topics.snapshot()
        data["topic_config_error"] = groups.error
        data["topic_modes"] = [{"id": key, "label": mode["label"]}
                               for key, mode in groups.modes.items()]
        snapshots = {
            key: json.dumps({**data, "topic_mode": key,
                             "camera_topics": groups.image_topics(key),
                             "camera_topics_by_mode": {mode: groups.image_topics(mode)
                                                       for mode in groups.modes},
                             "camera_default_fps": groups.camera["fps"],
                             "topic_groups": groups.classify(received, key, reload=False)},
                            ensure_ascii=False, separators=(",", ":"))
            for key in groups.modes
        }

    async def sampler():
        while True:
            await asyncio.sleep(1)
            sample()

    async def monitoring(app):
        sample()
        task = asyncio.create_task(sampler())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def shutdown(app):
        await asyncio.gather(*(ws.close(code=1001, message=b"Server shutdown") for ws in list(sockets)))

    async def index(request: web.Request) -> web.Response:
        # 이전: return web.Response(text=page, content_type="text/html", charset="utf-8",
        # Apply the same explicit route to the initial external script request.
        # 사용자 현재 환경: Tailscale + VS Code SSH 터널을 통한 인터넷 원격 접속.
        # 이전: internet = "0" if request.query.get("internet") == "0" else "1"
        internet = "1"  # 모든 대시보드 접속을 외부 접속으로 간주.
        body = page.replace('src="/gps.js"', f'src="/gps.js?internet={internet}"')
        return web.Response(text=body, content_type="text/html", charset="utf-8",
                            headers={"Cache-Control": "no-cache"})

    async def bev_vehicle(request):
        # 이전 코드: return web.FileResponse(Path(__file__).with_name("assets") / "ego-vehicle-top-v1.png")
        # 이전 코드: return web.FileResponse(Path(__file__).with_name("assets") / "ego-vehicle-icon-v2.png")
        return web.FileResponse(Path(__file__).with_name("assets") / "ego-vehicle-outline-v3.png")

    async def gps_tracks(request):
        path = Path(__file__).resolve().parent.parent / "data" / "gps-2026-09-20.json"
        if not path.is_file():
            raise web.HTTPServiceUnavailable(text="GPS data not exported")
        return web.Response(body=await asyncio.to_thread(path.read_bytes), content_type="application/json")

    async def gps_script(request):
        # 이전 흰 박스 지도 스크립트:
        # return web.Response(body=Path(__file__).with_name("gps.js").read_bytes(), content_type="application/javascript")
        return web.Response(body=Path(__file__).with_name("gps-live-overlay.js").read_bytes(), content_type="application/javascript")

    async def relative_asset(request):
        files = {
            '/map-compare-live.js': (Path(__file__).with_name('map-compare-live.js'), 'application/javascript'),
            '/map-compare.js': (Path(__file__).with_name('map-compare.js'), 'application/javascript'),
            '/map-compare.css': (Path(__file__).with_name('map-compare.css'), 'text/css'),
            '/map-position.js': (Path(__file__).with_name('map-position.js'), 'application/javascript'),
            '/map-position.css': (Path(__file__).with_name('map-position.css'), 'text/css'),
            '/gps-export.js': (Path(__file__).with_name('gps-export.js'), 'application/javascript'),
            '/gps-camera-projection.js': (Path(__file__).with_name('gps-camera-projection.js'), 'application/javascript'),
            '/gps-map-replay.js': (Path(__file__).with_name('gps-map-replay.js'), 'application/javascript'),
            '/gps-final-points.js': (Path(__file__).with_name('gps-final-points.js'), 'application/javascript'),
            '/gps-sections.js': (Path(__file__).with_name('gps-sections.js'), 'application/javascript'),
            '/gps-lane.js': (Path(__file__).with_name('gps-lane.js'), 'application/javascript'),
            '/gps-path.js': (Path(__file__).with_name('gps-path.js'), 'application/javascript'),
            '/gps-ordering.js': (Path(__file__).with_name('gps-ordering.js'), 'application/javascript'),
            '/gps-fusion.js': (Path(__file__).with_name('gps-fusion.js'), 'application/javascript'),
            '/gps-map-merge.js': (Path(__file__).with_name('gps-map-merge.js'), 'application/javascript'),
            '/gps-project.js': (Path(__file__).with_name('gps-project.js'), 'application/javascript'),
            '/gps-additions.js': (Path(__file__).with_name('gps-additions.js'), 'application/javascript'),
            '/gps-merge.js': (Path(__file__).with_name('gps-merge.js'), 'application/javascript'),
            '/gps-test.js': (Path(__file__).with_name('gps-test.js'), 'application/javascript'),
            '/dashboard-modes.js': (Path(__file__).with_name('dashboard-modes.js'), 'application/javascript'),
            '/relative-surface.js': (Path(__file__).with_name('relative-surface.js'), 'application/javascript'),
            '/relative-map.js': (Path(__file__).with_name('relative-map.js'), 'application/javascript'),
            '/api/relative-map/summary': (Path(__file__).resolve().parent.parent / 'data/relative-map/summary.json', 'application/json'),
            '/api/relative-map/points': (Path(__file__).resolve().parent.parent / 'data/relative-map/points.f32', 'application/octet-stream'),
        }
        path, kind = files[request.path]
        if not path.is_file():
            raise web.HTTPNotFound(text='Relative map unavailable')
        return web.Response(body=await asyncio.to_thread(path.read_bytes), content_type=kind)

    async def traffic(request: web.Request) -> web.WebSocketResponse:
        ws = ViewerWebSocket(browser, heartbeat=20, compress=False, max_msg_size=1024)
        await ws.prepare(request)
        sockets.add(ws)
        mode = request.query.get("mode", groups.default_mode)

        async def send_snapshot():
            nonlocal mode
            if mode not in snapshots:
                mode = groups.default_mode
            await asyncio.wait_for(ws.send_str(snapshots[mode]), timeout=5)

        async def send():
            try:
                while not ws.closed:
                    await send_snapshot()
                    await asyncio.sleep(1)
            except (ConnectionError, asyncio.TimeoutError):
                await ws.close()

        sender = asyncio.create_task(send())
        try:
            async for message in ws:
                if message.type == web.WSMsgType.ERROR:
                    break
                if message.type == web.WSMsgType.TEXT:
                    try:
                        selection = json.loads(message.data)
                    except ValueError:
                        continue
                    selected = selection.get("mode") if isinstance(selection, dict) else None
                    if isinstance(selected, str) and selected in snapshots:
                        mode = selected
                        await send_snapshot()
        finally:
            sender.cancel()
            with suppress(asyncio.CancelledError, ConnectionError):
                await sender
            sockets.discard(ws)
        return ws

    async def receive_topics(request: web.Request) -> web.Response:
        try:
            topics.update(await request.json())
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="Invalid topic report")
        return web.Response(status=204)

    app = web.Application(client_max_size=CameraHub.MAX_FRAME_BYTES, middlewares=[count_page_traffic])
    app[BROWSER_TRAFFIC] = browser
    origin_path = Path(__file__).resolve().parent.parent / "data" / "gps-2026-09-20.json"
    origin = json.loads(origin_path.read_text())["origin"] if origin_path.is_file() else None
    gps = GPSLive(origin)
    gps.add_routes(app, browser)
    add_monitor_1021_routes(app)
    add_gps_map_routes(app)
    add_map_position_routes(app)
    add_map_compare_routes(app)
    add_gps_review_routes(app)
    add_gps_workflow_routes(app)
    add_gps_project_routes(app)
    add_gps_source_routes(app)
    add_bag_routes(app)
    camera.add_routes(app)
    add_brake_routes(app, browser)
    app.cleanup_ctx.append(monitoring)
    app.on_shutdown.append(shutdown)
    app.router.add_get("/", index)
    # 이전 코드: app.router.add_get("/assets/ego-vehicle-top-v1.png", bev_vehicle)
    # 이전 코드: app.router.add_get("/assets/ego-vehicle-icon-v2.png", bev_vehicle)
    app.router.add_get("/assets/ego-vehicle-outline-v3.png", bev_vehicle)
    app.router.add_get("/api/gps/tracks", gps_tracks)
    app.router.add_get("/gps.js", gps_script)
    app.router.add_get('/map-compare-live.js',relative_asset)
    app.router.add_get('/map-compare.js',relative_asset)
    app.router.add_get('/map-compare.css',relative_asset)
    app.router.add_get('/map-position.js',relative_asset)
    app.router.add_get('/map-position.css',relative_asset)
    for route in ("/gps-final-points.js", "/gps-map-merge.js", "/gps-camera-projection.js", "/gps-sections.js", "/gps-export.js", "/gps-map-replay.js", "/gps-lane.js", "/gps-path.js", "/gps-ordering.js", "/gps-fusion.js", "/gps-project.js", "/gps-additions.js", "/gps-merge.js", "/gps-test.js", "/dashboard-modes.js", "/relative-surface.js", "/relative-map.js", "/api/relative-map/summary", "/api/relative-map/points"):
        if route.startswith("/api/relative-map/") or route in ("/relative-map.js", "/relative-surface.js"):
            continue
        app.router.add_get(route, relative_asset)
    app.router.add_get("/ws/traffic", traffic)
    app.router.add_post("/api/ros/topics", receive_topics)
    return app


def main() -> None:
    asyncio.run(serve(
        create_app(),
        host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("DASHBOARD_PORT", "8080")),
    ))


if __name__ == "__main__":
    main()
