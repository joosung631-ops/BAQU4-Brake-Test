import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from scipy.optimize._numdiff import approx_derivative
from dashboard.gps_path import Curve, coordinates_to_gps, generate_path, vehicle_config, single_path_result, path_source
from dashboard.gps_review import project, digest
from dashboard.gps_project import add_routes

VEHICLE = {'wheelbase_m':1.328,'max_front_steering_left_deg':30,'max_front_steering_right_deg':30,
           'gps_antenna_offset_x_m':.559,'gps_antenna_offset_y_m':0.,
           'path_reference_offset_x_m':0.,'path_reference_offset_y_m':0.}


def document(xy):
    origin=[37.,127.]
    ll=coordinates_to_gps(np.asarray(xy,dtype=float),origin)
    pts=[{'index':i+1,'point_index':i,'lat':float(a),'lon':float(b)} for i,(a,b) in enumerate(ll)]
    return {'format':'gps-map-project','version':3,'revision':1,'stages':{'1':{},'2':{'raw':{'origin':origin}},
            '7':{'ordered_points':pts,'matches':[{'segment_index':0} for _ in pts]}}}


class PathTests(unittest.TestCase):
    def test_geographic_roundtrip(self):
        xy=np.array([[0.,0.],[501.,-321.],[-500.,800.]])
        gps=coordinates_to_gps(xy,[37,127]);pts=project([{'lat':p[0],'lon':p[1]} for p in gps],[37,127])
        np.testing.assert_allclose([[p['e'],p['n']] for p in pts],xy,atol=1e-7)

    def test_analytic_jacobians(self):
        knots=np.r_[np.zeros(4),[2.,4.],np.full(4,6.)]
        curve=Curve(knots,np.linspace(0,6,11),(.559,.1))
        z=np.r_[np.linspace(0,6,6),[0,.1,.4,.8,1.,1.2]]
        v=curve.evaluate(z,True)
        qx=approx_derivative(lambda x:curve.evaluate(x)[1][:,0],z)
        qy=approx_derivative(lambda x:curve.evaluate(x)[1][:,1],z)
        jk=approx_derivative(lambda x:curve.evaluate(x)[2],z)
        np.testing.assert_allclose(v[5],qx,atol=1e-6)
        np.testing.assert_allclose(v[6],qy,atol=1e-6)
        np.testing.assert_allclose(v[7],jk,atol=1e-6)

    def test_straight_lever_arm_open_endpoints_and_ten_cm(self):
        d=document([[0,0],[2,0],[5,0]])
        r=generate_path(d,VEHICLE,{'max_deviation_m':.05,'smoothing':1})
        self.assertTrue(r['valid'],r['validation'])
        self.assertAlmostEqual(r['points'][0]['e'],-.559,places=5)
        self.assertAlmostEqual(r['points'][-1]['e'],5-.559,places=5)
        self.assertFalse(r['settings']['closed'])
        ds=np.diff([p['s_m'] for p in r['points']])
        np.testing.assert_allclose(ds[:-1],.1,atol=1e-7)
        self.assertLessEqual(ds[-1],.1000001)
        self.assertLess(r['statistics']['distance_max_m'],1e-5)

    def test_feasible_arc_and_infeasible_tight_turn(self):
        for radius,tolerance,expected in [(10.,.1,True),(1.,.002,False)]:
            angle=np.linspace(0,1.2,25)
            rear=np.column_stack((radius*np.sin(angle),radius*(1-np.cos(angle))))
            gps=rear+.559*np.column_stack((np.cos(angle),np.sin(angle)))
            r=generate_path(document(gps),VEHICLE,{'max_deviation_m':tolerance,'smoothing':.1})
            self.assertEqual(r['valid'],expected,r['validation'])
            if expected:
                self.assertLessEqual(r['statistics']['max_abs_steering_deg'],30.001)
                self.assertLessEqual(r['statistics']['distance_max_m'],tolerance+.0001)
                chords=np.linalg.norm(np.diff([[p['e'],p['n']] for p in r['points']],axis=0),axis=1)
                self.assertLessEqual(chords.max(),.10001)
                self.assertGreater(chords[:-1].min(),.0998)

    def test_four_meter_straight_gaps_do_not_wiggle_near_a_turn(self):
        # Long straight sections with sparse observations, joined by a genuine curve.
        x=np.arange(0.,40.,4.)
        rear1=np.column_stack((x,np.zeros_like(x)))
        a=np.linspace(0,np.pi/2,9)
        rear2=np.column_stack((40+8*np.sin(a),8*(1-np.cos(a))))
        y=np.arange(12.,49.,4.)
        rear3=np.column_stack((np.full_like(y,48.),y))
        rear=np.vstack((rear1,rear2,rear3))
        yaw=np.r_[np.zeros(len(x)),a,np.full(len(y),np.pi/2)]
        gps=rear+.559*np.column_stack((np.cos(yaw),np.sin(yaw)))
        r=generate_path(document(gps),VEHICLE,{'max_deviation_m':.2,'smoothing':1})
        self.assertTrue(r['valid'],r['validation'])
        straight=[p for p in r['points'] if 8<p['e']<28 and p['n']<1]
        self.assertGreater(len(straight),150)
        self.assertLess(max(abs(p['n']) for p in straight),.03)
        self.assertLess(max(abs(p['steering_deg']) for p in straight),.5)

    def test_config_comments_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'vehicle.jsonc';p.write_text('// comment\n'+json.dumps(VEHICLE))
            with patch.dict(os.environ,{'DASHBOARD_VEHICLE_CONFIG':str(p)}):
                self.assertEqual(vehicle_config(),VEHICLE)
                p.write_text(json.dumps({**VEHICLE,'wheelbase_m':None}))
                with self.assertRaises(web.HTTPBadRequest):vehicle_config()
        for settings in ({'max_deviation_m':True,'smoothing':1},{'max_deviation_m':.2,'smoothing':float('nan')}):
            with self.assertRaises(web.HTTPBadRequest):generate_path(document([[0,0],[1,0]]),VEHICLE,settings)

    def test_single_storage_and_lossless_legacy_conversion(self):
        result=generate_path(document([[0,0],[2,0],[5,0]]),VEHICLE,{'max_deviation_m':.1,'smoothing':1})
        self.assertNotIn('segments',result);self.assertNotIn('samples',result)
        self.assertEqual(result['format_version'],2)
        info=('matches','spline','validation','violations')
        legacy={k:v for k,v in result.items() if k not in (*info,'format_version')}
        legacy['segments']=[{**{k:result[k] for k in info},'valid':True,'samples':[{k:v for k,v in p.items() if k!='index'} for p in result['points']]}]
        legacy['points']=[{**p,'segment_index':0,'break_before':i==0} for i,p in enumerate(result['points'])]
        self.assertEqual(single_path_result(legacy),result)
        self.assertEqual(single_path_result(result),result)
        legacy['segments'][0]['samples'][0]['e']+=1
        with self.assertRaises(web.HTTPConflict):single_path_result(legacy)

    def test_waypoint_identity_validation_order_and_projection(self):
        d=document([[0,0],[2,0],[5,0]])
        lat,lon=coordinates_to_gps(np.array([[3.,0.]]),[37.,127.])[0]
        edit=[{'id':'source-1'},{'id':'manual-insert','lat':float(lat),'lon':float(lon),'segment_index':0},{'id':'source-3'}]
        source=path_source(d,edit)
        self.assertEqual([p['index'] for p in source['points']],[1,2,3])
        self.assertEqual([p['source_index'] for p in source['points']],[1,None,3])
        self.assertAlmostEqual(source['points'][1]['e'],3.,places=7)
        self.assertEqual(source['waypoints'],edit)
        self.assertEqual(len(d['stages']['7']['ordered_points']),3)
        original=path_source(d,[{'id':'source-1','lat':0,'lon':0}])['points'][0]
        self.assertEqual(original['lat'],37.) # source coordinates cannot be forged
        bad=[None,[{'id':'source-99'}],[edit[0],edit[0]],
             [{**edit[1],'lat':True}],[{**edit[1],'lon':float('nan')}],
             [{**edit[1],'segment_index':1}],[{**edit[1],'segment_index':False}],
             [{**edit[1],'id':'manual-'}]]
        for spec in bad:
            if spec is None:spec={'not':'list'}
            with self.subTest(spec=spec),self.assertRaises(web.HTTPBadRequest):path_source(d,spec)
        self.assertEqual(path_source(d,[])['points'],[])
        with self.assertRaises(web.HTTPBadRequest):generate_path(d,VEHICLE,{'max_deviation_m':.1,'smoothing':1},[])
        d['stages']['8']={'source_digest':digest(d['stages']['7']),'waypoints':edit,'draft':True}
        self.assertEqual(path_source(d)['waypoints'],edit)
        d['stages']['8']['source_digest']='stale'
        self.assertEqual(len(path_source(d)['points']),3)
        self.assertFalse(any(p['manual'] for p in path_source(d)['points']))

    def test_gaps_not_joined(self):
        d=document([[0,0],[2,0],[20,0],[22,0]])
        for m in d['stages']['7']['matches'][2:]:m['segment_index']=1
        with self.assertRaises(web.HTTPBadRequest) as error:
            generate_path(d,VEHICLE,{'max_deviation_m':.1,'smoothing':1})
        self.assertIn('#2와 #3',error.exception.text)


class PathApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=self.root/'vehicle.jsonc';self.config.write_text(json.dumps(VEHICLE))
        self.env=patch.dict(os.environ,{'DASHBOARD_GPS_REVIEW_DIR':str(self.root/'review'),'DASHBOARD_VEHICLE_CONFIG':str(self.config)});self.env.start()
        maps=self.root/'review/maps';maps.mkdir(parents=True)
        self.doc=document([[0,0],[2,0],[5,0]]);self.file=maps/'path.json';self.file.write_text(json.dumps(self.doc))
        app=web.Application();add_routes(app);self.client=TestClient(TestServer(app));await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();self.env.stop();self.tmp.cleanup()
    async def post(self,route,body,status=200):
        r=await self.client.post('/api/gps/projects/'+route,json=body,headers={'X-Dashboard-Control':'1'})
        self.assertEqual(r.status,status,await r.text())
        return await r.json() if status==200 else None
    async def test_preview_save_restore_stale_config_and_rewind(self):
        source=await (await self.client.get('/api/gps/projects/path-source?filename=path.json')).json()
        before=self.file.read_bytes()
        preview=await self.post('path-preview',{'filename':'path.json','source_digest':source['source_digest'],'settings':{'max_deviation_m':.1,'smoothing':1}})
        self.assertEqual(self.file.read_bytes(),before)
        body={'filename':'path.json','revision':1,'stage':8,'source_digest':source['source_digest'],'preview_id':preview['preview_id']}
        await self.post('save',{**body,'preview_id':'forged'},409)
        self.config.write_text(json.dumps({**VEHICLE,'max_front_steering_left_deg':29}))
        await self.post('save',body,409)
        self.config.write_text(json.dumps(VEHICLE))
        saved=await self.post('save',body)
        self.assertEqual(saved['project']['stages']['8']['vehicle_config'],VEHICLE)
        loaded=await (await self.client.get('/api/gps/projects/path-source?filename=path.json')).json()
        self.assertEqual(loaded['saved']['points'],preview['result']['points'])
        await self.post('save',body,409)
        rewound=await self.post('rewind',{'filename':'path.json','revision':saved['project']['revision'],'stage':7})
        self.assertNotIn('8',rewound['project']['stages'])

    async def test_edit_draft_roundtrip_and_preview_binding(self):
        source=await (await self.client.get('/api/gps/projects/path-source?filename=path.json')).json()
        lat,lon=coordinates_to_gps(np.array([[3.,0.]]),[37.,127.])[0]
        edit=[{'id':'source-1'},{'id':'manual-new','lat':float(lat),'lon':float(lon),'segment_index':0},{'id':'source-3'}]
        settings={'max_deviation_m':.1,'smoothing':1}
        self.doc['stages'].update({'9':{'sentinel':True},'10':{},'11':{}})
        self.file.write_text(json.dumps(self.doc));original=self.doc['stages']['7']
        draft=await self.post('save',{'filename':'path.json','revision':1,'stage':8,'draft':True,'source_digest':source['source_digest'],'waypoints':edit,'settings':settings})
        self.assertTrue(draft['project']['stages']['8']['draft'])
        self.assertEqual(draft['project']['stages']['7'],original)
        for stage in ('9','10','11'):self.assertNotIn(stage,draft['project']['stages'])
        loaded=await (await self.client.get('/api/gps/projects/path-source?filename=path.json')).json()
        self.assertEqual(loaded['waypoints'],edit)
        self.assertEqual(loaded['points'][1]['id'],'manual-new')
        response=await self.client.get('/api/gps/projects/lane-source?filename=path.json')
        self.assertEqual(response.status,200)
        self.assertEqual((await response.json())['interpolation'],'piecewise_linear')
        preview=await self.post('path-preview',{'filename':'path.json','source_digest':source['source_digest'],'settings':settings,'waypoints':edit})
        self.assertTrue(preview['result']['valid'])
        self.assertEqual(len(preview['result']['matches']),3)
        body={'filename':'path.json','revision':draft['project']['revision'],'stage':8,'source_digest':source['source_digest'],'preview_id':preview['preview_id']}
        await self.post('save',{**body,'waypoints':edit[:2]},409)
        saved=await self.post('save',{**body,'waypoints':edit})
        self.assertEqual(saved['project']['stages']['8']['waypoints'],edit)
        self.assertTrue(saved['project']['stages']['8']['valid'])
        await self.post('save',{'filename':'path.json','revision':saved['project']['revision'],'stage':8,'draft':True,'source_digest':source['source_digest'],'waypoints':[],'settings':settings})
        empty=await (await self.client.get('/api/gps/projects/path-source?filename=path.json')).json()
        self.assertEqual(empty['points'],[])
        self.assertEqual(empty['segment_indexes'],[0])
