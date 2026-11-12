"""Read generated GPS maps from the configured, read-only map directory."""
import asyncio
import json
from .gps_review import identify
import os
import re
from pathlib import Path

from aiohttp import web


def add_routes(app):
    root = Path(os.environ.get('DASHBOARD_GPS_MAP_DIR',
                Path(__file__).resolve().parents[2] / 'main/decision/script/map_generator')).resolve()

    def allowed(path):
        return path.suffix == '.json' and not path.is_symlink() and path.is_file()

    async def listing(request):
        def names():
            return sorted(p.name for p in root.glob('*.json') if allowed(p))
        return web.json_response({'maps': await asyncio.to_thread(names)},
                                 headers={'Cache-Control': 'no-store'})

    async def load(request):
        name = request.match_info['name']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise web.HTTPNotFound()
        path = root / name
        if not allowed(path):
            raise web.HTTPNotFound(text='GPS map not found')
        try:
            body = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise web.HTTPNotFound(text='GPS map not found')
        except PermissionError:
            raise web.HTTPForbidden(text='GPS map is not readable')
        return web.Response(body=body, content_type='application/json',
                            headers={'Cache-Control': 'no-store'})

    async def test_raw(request):
        path = root / 'test' / 'raw.json'
        if not allowed(path):
            raise web.HTTPNotFound(text='테스트 GPS를 먼저 내보내세요.')
        data = json.loads(await asyncio.to_thread(path.read_text))
        if data.get('tracks') is not None:
            _, data['review_dataset_id'] = identify(data)
        return web.json_response(data, headers={'Cache-Control': 'no-store'})

    async def test_frame(request):
        name = request.match_info['name']
        if not re.fullmatch(r'[0-9a-f]{64}\.(jpg|png)', name):
            raise web.HTTPNotFound()
        path = root / 'test' / 'frames' / name
        if not path.is_file() or path.is_symlink():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Cache-Control': 'public, max-age=31536000, immutable'})

    app.router.add_get('/api/gps/test/frames/{name}', test_frame)
    app.router.add_get('/api/gps/test', test_raw)
    app.router.add_get('/api/gps/maps', listing)
    app.router.add_get('/api/gps/maps/{name}', load)
