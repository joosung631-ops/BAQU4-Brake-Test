"""Same-origin UI proxy to the main container's loopback-only ROS bag owner."""
import asyncio
from pathlib import Path
from urllib.parse import urlencode
import aiohttp
from aiohttp import web


def add_routes(app):
    async def proxy(request):
        action = request.match_info.get('action', '')
        if request.method == 'POST':
            if request.headers.get('X-Dashboard-Control') != '1' or request.content_type != 'application/json':
                raise web.HTTPForbidden()
            if request.content_length is None or request.content_length > 1024:
                raise web.HTTPBadRequest()
            try: data = await request.json()
            except ValueError: raise web.HTTPBadRequest()
            target = '/' + action
        else:
            data = None
            target = '/track?' + urlencode({'bag':request.query.get('bag', '')}) if action == 'track' else '/bags'
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.request(request.method, 'http://127.0.0.1:8768'+target,
                                           json=data, headers={'X-Dashboard-Control':'1'}) as response:
                    return web.json_response(await response.json(), status=response.status,
                                             headers={'Cache-Control':'no-store'})
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return web.json_response({'error':'main의 bag 제어기에 연결할 수 없습니다.'}, status=503)
    async def script(request):
        return web.Response(text=Path(__file__).with_name('bag-control.js').read_text(),
                            content_type='application/javascript')
    app.router.add_get('/api/bags', proxy)
    app.router.add_get('/api/bags/{action:track}', proxy)
    app.router.add_post('/api/bags/{action:play|stop|rate}', proxy)
    app.router.add_get('/bag-control.js', script)
