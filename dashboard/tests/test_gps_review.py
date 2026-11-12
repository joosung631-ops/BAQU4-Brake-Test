import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from dashboard.gps_review import add_routes, build_review, curve_segment, identify, smooth


class CurveTests(unittest.TestCase):
    def test_regularized_solution_and_straight_line(self):
        y=[0.,1.,-1.,2.,0.,1.,0.];strength=5
        z=smooth(y,strength)
        # Verify normal equations, not just a mirrored implementation output.
        gradient=[a-b for a,b in zip(z,y)]
        for i in range(len(y)-2):
            d=z[i]-2*z[i+1]+z[i+2]
            for j,c in enumerate((1,-2,1)):gradient[i+j]+=strength*c*d
        self.assertLess(max(map(abs,gradient)),1e-10)
        self.assertLess(sum((z[i]-2*z[i+1]+z[i+2])**2 for i in range(5)),
                        sum((y[i]-2*y[i+1]+y[i+2])**2 for i in range(5)))
        for a,b in zip(smooth([0,1,2,3,4],20),[0,1,2,3,4]):self.assertAlmostEqual(a,b)

    def test_dwell_density_and_small_inputs(self):
        pts=[{'e':0.,'n':0.,'seq':1},{'e':1.,'n':1.,'seq':2},{'e':2.,'n':0.,'seq':3}]
        a=curve_segment(pts,.5);b=curve_segment([pts[0]]*100+pts[1:],.5)
        self.assertEqual(a,b)
        self.assertEqual(curve_segment([],1),[])
        self.assertEqual(len(curve_segment(pts[:1],1)),1)
        self.assertTrue(all(math.isfinite(p['e']) and math.isfinite(p['n']) for p in a))

    def test_gap_and_exclusion(self):
        t={'id':'x','name':'a','points':[{'seq':i,'lat':37+i*.00001,'lon':127.,'break_before':i==3} for i in range(1,6)]}
        review=build_review(t,[37,127],[3],.5)
        self.assertEqual([p['seq'] for p in review['retained_points']],[1,2,4,5])
        self.assertEqual(len(review['curve_segments']),2)
        self.assertEqual(build_review(t,[37,127],[1,2,3,4,5],.5)['curve_segments'],[])

    def test_range_trimming_and_manual_exclusion(self):
        t={'id':'x','name':'a','points':[{'seq':i,'lat':37+i*.00001,'lon':127.} for i in range(1,7)]}
        result=build_review(t,[37,127],[3],.5,start_seq=2,end_seq=5)
        self.assertEqual(result['excluded_seq'],[1,3,6])
        self.assertEqual(result['manual_excluded_seq'],[3])
        self.assertEqual([p['seq'] for p in result['retained_points']],[2,4,5])
        reset=build_review(t,[37,127],result['manual_excluded_seq'],.5)
        self.assertEqual(reset['excluded_seq'],[3])
        self.assertEqual(len(build_review(t,[37,127],[],.5,start_seq=4,end_seq=4)['retained_points']),1)
        for start,end in [(5,2),(0,4),(2,99),(True,4)]:
            with self.assertRaises(ValueError):build_review(t,[37,127],[],.5,start_seq=start,end_seq=end)


class ReviewAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'test').mkdir()
        self.raw={'origin':[37,127],'tracks':[{'name':'a','points':[
            {'seq':i,'lat':37+i*.00001,'lon':127.,'recorded_ns':str(i)} for i in range(1,5)]}]}
        (self.root/'test/raw.json').write_text(json.dumps(self.raw))
        with patch.dict(os.environ,{'DASHBOARD_GPS_MAP_DIR':str(self.root),'DASHBOARD_GPS_REVIEW_DIR':str(self.root/'review')}):
            app=web.Application();add_routes(app)
        self.client=TestClient(TestServer(app));await self.client.start_server()
        self.headers={'X-Dashboard-Control':'1'}

    async def asyncTearDown(self):
        await self.client.close();self.tmp.cleanup()

    async def state(self):return await (await self.client.get('/api/gps/review')).json()

    async def test_save_reload_retained_points_and_conflict(self):
        state=await self.state();track=state['tracks'][0]
        body={'dataset_id':state['dataset_id'],'revision':state['revision'],'tracks':[
            {'id':track['id'],'excluded_seq':[2],'smoothing_m':1.,'complete':True}]}
        preview=await self.client.post('/api/gps/review/preview',json=body,headers=self.headers)
        self.assertEqual(preview.status,200);self.assertFalse((self.root/'review/review.json').exists())
        response=await self.client.post('/api/gps/review',json=body,headers=self.headers)
        self.assertEqual(response.status,200)
        saved=json.loads((self.root/'review/review.json').read_text())
        t=saved['tracks'][track['id']]
        self.assertEqual([p['seq'] for p in t['retained_points']],[1,3,4]);self.assertTrue(t['complete'])
        restored=await self.state();self.assertEqual(restored['tracks'][0]['excluded_seq'],[2])
        response=await self.client.post('/api/gps/review',json=body,headers=self.headers)
        self.assertEqual(response.status,409)
        self.raw['tracks'].append({'name':'b','points':self.raw['tracks'][0]['points']})
        (self.root/'test/raw.json').write_text(json.dumps(self.raw))
        expanded=await self.state()
        self.assertEqual(expanded['tracks'][0]['excluded_seq'],[2]);self.assertEqual(expanded['tracks'][1]['excluded_seq'],[])
        body['revision']=1
        response=await self.client.post('/api/gps/review',json=body,headers=self.headers)
        self.assertEqual(response.status,409)

    async def test_invalid_request_cannot_write(self):
        state=await self.state();track=state['tracks'][0]
        for excluded,smoothing in [([999],.5),([True],.5),([],float('nan')),([],11)]:
            body={'dataset_id':state['dataset_id'],'revision':0,'tracks':[
                {'id':track['id'],'excluded_seq':excluded,'smoothing_m':smoothing}]}
            response=await self.client.post('/api/gps/review',json=body,headers=self.headers)
            self.assertEqual(response.status,400)
        response=await self.client.post('/api/gps/review',json={})
        self.assertEqual(response.status,403)
        self.assertFalse((self.root/'review/review.json').exists())
