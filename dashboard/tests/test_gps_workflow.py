import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from dashboard.gps_workflow import add_routes, merge_tracks, save_snapshot
from dashboard.gps_review import add_routes as reviews


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'DASHBOARD_GPS_MAP_DIR':str(self.root),'DASHBOARD_GPS_REVIEW_DIR':str(self.root/'review')});self.env.start()
        (self.root/'test').mkdir()
        (self.root/'test/raw.json').write_text(json.dumps({'origin':[37,127],'tracks':[{'name':'bag','points':[
            {'seq':i,'lat':37+i*.00001,'lon':127.,'break_before':i==4} for i in range(1,6)]}]}))
        app=web.Application();reviews(app);add_routes(app);self.client=TestClient(TestServer(app));await self.client.start_server()
        self.headers={'X-Dashboard-Control':'1'}
    async def asyncTearDown(self):
        await self.client.close();self.env.stop();self.tmp.cleanup()
    async def stage1(self):
        r=await self.client.get('/api/gps/review');data=await r.json()
        payload={'dataset_id':data['dataset_id'],'revision':data['revision'],'filename':'2026-09-26-120000-노이즈.json','tracks':[{'id':data['tracks'][0]['id'],'excluded_seq':[2]}]}
        r=await self.client.post('/api/gps/review',json=payload,headers=self.headers);self.assertEqual(r.status,200,await r.text())
        return payload,await r.json()
    async def test_save_merge_reload_and_provenance(self):
        _,saved=await self.stage1();self.assertTrue(Path(saved['path']).exists())
        r=await self.client.get('/api/gps/stages/load',params={'filename':saved['filename']});data=await r.json();source=data['source'];t=source['tracks'][0]
        self.assertEqual([p['seq'] for p in t['points']],[1,3,4,5]);self.assertNotIn('curve_segments',t)
        payload={'source_file':saved['filename'],'filename':'2026-09-26-120001-병합.json','tracks':[{'id':t['id'],'groups':[[1,3],[4,5]]}]}
        r=await self.client.post('/api/gps/stages/merge',json=payload,headers=self.headers);self.assertEqual(r.status,200,await r.text())
        r=await self.client.get('/api/gps/stages/load',params={'filename':payload['filename']});loaded=await r.json()
        p=loaded['data']['tracks'][0]['points'][0];self.assertEqual(p['source_seqs'],[1,3]);self.assertAlmostEqual(p['lat'],37.00002)
        self.assertEqual(loaded['source'],source)
        r=await self.client.post('/api/gps/stages/merge',json=payload,headers=self.headers);self.assertEqual(r.status,409)
        for groups in ([[1,4],[3,5]],[[1,3,4],[5]],[[1,1],[4,5]],[[1],[3],[4]]):
            with self.assertRaises(web.HTTPBadRequest):merge_tracks(source,[{'id':t['id'],'groups':groups}])
    async def test_names_and_collision_do_not_update_review(self):
        payload,saved=await self.stage1();before=(self.root/'review/review.json').read_bytes();payload['revision']=1
        for filename,code in [(saved['filename'],409),('../escape.json',400)]:
            payload['filename']=filename
            r=await self.client.post('/api/gps/review',json=payload,headers=self.headers);self.assertEqual(r.status,code)
            self.assertEqual((self.root/'review/review.json').read_bytes(),before)
    async def test_original_weighting_and_empty_track(self):
        source={'tracks':[{'id':'a','name':'a','points':[{'seq':i,'lat':v,'lon':0,'segment':0} for i,v in [(1,0),(2,2),(3,10)]]}]}
        result=merge_tracks(source,[{'id':'a','groups':[[1,2,3]]}]);self.assertEqual(result[0]['points'][0]['lat'],4)
        self.assertEqual(merge_tracks({'tracks':[{'id':'a','name':'a','points':[]}]},[{'id':'a','groups':[]}])[0]['points'],[])
