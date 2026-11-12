import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from dashboard.bag_control import add_routes


class BagProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_track_proxy_keeps_unicode_path_and_read_only_method(self):
        requests = []
        async def upstream(request):
            requests.append((request.method, request.path, request.query.get('bag')))
            return web.json_response({'phase':'done','bag':request.query['bag'],'points':[]})
        source=web.Application();source.router.add_get('/track',upstream)
        app=web.Application();add_routes(app)
        async with TestServer(source,port=8768), TestClient(TestServer(app)) as client:
            bag='2026-10-25/01_예선_중간정지'
            response=await client.get('/api/bags/track',params={'bag':bag})
            self.assertEqual(response.status,200)
            self.assertEqual((await response.json())['bag'],bag)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(requests,[('GET','/track',bag)])

    async def test_track_error_and_running_status_are_forwarded(self):
        async def upstream(request):
            if request.query.get('bag')=='missing':
                return web.json_response({'error':'목록에서 선택하세요.'},status=400)
            return web.json_response({'phase':'running','bag':'recording'})
        source=web.Application();source.router.add_get('/track',upstream)
        app=web.Application();add_routes(app)
        async with TestServer(source,port=8768), TestClient(TestServer(app)) as client:
            response=await client.get('/api/bags/track?bag=recording')
            self.assertEqual((await response.json())['phase'],'running')
            response=await client.get('/api/bags/track?bag=missing')
            self.assertEqual(response.status,400)

    async def test_new_read_route_does_not_bypass_play_control_header(self):
        app=web.Application();add_routes(app)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/bags/play',json={'bag':'recording'})
            self.assertEqual(response.status,403)
            response=await client.post('/api/bags/track',json={'bag':'recording'})
            self.assertEqual(response.status,405)


if __name__=='__main__': unittest.main()
