import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from dashboard.gps_lane import lane_edges, road_config, lane_source
from dashboard.gps_review import digest
from test_gps_path import document
from dashboard.gps_project import add_routes

class LaneTests(unittest.TestCase):
    def test_normal_offsets_follow_heading(self):
        points=[{'e':i,'n':2*i,'heading_rad':angle} for i,angle in enumerate([0,math.pi/2,math.pi,-math.pi/2,.7])]
        edges=lane_edges(points,3.2)
        for p,l,r in zip(points,edges['left'],edges['right']):
            self.assertAlmostEqual(math.hypot(l['e']-p['e'],l['n']-p['n']),1.6)
            self.assertAlmostEqual(math.hypot(l['e']-r['e'],l['n']-r['n']),3.2)
            self.assertAlmostEqual((l['e']-p['e'])*math.cos(p['heading_rad'])+(l['n']-p['n'])*math.sin(p['heading_rad']),0)
        self.assertEqual(edges['left'][0],{'e':0.,'n':1.6})
        self.assertAlmostEqual(edges['left'][1]['e'],-.6)
    def test_width_validation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'road.jsonc'
            with patch.dict(os.environ,{'DASHBOARD_ROAD_CONFIG':str(p)}):
                for v in [None,0,-1,True,'3',float('nan')]:
                    p.write_text(json.dumps({'lane_width_m':v}))
                    with self.assertRaises(web.HTTPBadRequest):road_config()
                p.write_text('// 전체 폭\n{"lane_width_m":3.2}')
                self.assertEqual(road_config()['lane_width_m'],3.2)

class LaneApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=self.root/'road.jsonc';self.config.write_text('{"lane_width_m":null}')
        self.env=patch.dict(os.environ,{'DASHBOARD_GPS_REVIEW_DIR':str(self.root/'review'),'DASHBOARD_ROAD_CONFIG':str(self.config)});self.env.start()
        maps=self.root/'review/maps';maps.mkdir(parents=True)
        self.doc=document([[0,0],[10,0]]);self.doc['stages']['8']={'draft':True,'valid':False,'source_digest':digest(self.doc['stages']['7'])}
        self.file=maps/'lane.json';self.file.write_text(json.dumps(self.doc))
        app=web.Application();add_routes(app);self.client=TestClient(TestServer(app));await self.client.start_server()
    async def asyncTearDown(self):await self.client.close();self.env.stop();self.tmp.cleanup()
    async def post(self,path,body,status=200):
        r=await self.client.post('/api/gps/projects/'+path,json=body,headers={'X-Dashboard-Control':'1'});self.assertEqual(r.status,status,await r.text());return await r.json() if status==200 else None
    async def source(self):return await (await self.client.get('/api/gps/projects/lane-source?filename=lane.json')).json()
    async def test_apply_save_snapshot_reload_and_rewind(self):
        source=await self.source();self.assertIsNone(source['edges']);self.assertIsNone(source['road_config']['lane_width_m'])
        body={'filename':'lane.json','source_digest':source['source_digest']}
        await self.post('lane-preview',body,400)
        self.config.write_text('{"lane_width_m":3.2}');before=self.file.read_bytes()
        preview=await self.post('lane-preview',body);self.assertEqual(before,self.file.read_bytes())
        save={**body,'stage':9,'revision':1,'road_digest':preview['settings']['road_digest']}
        self.config.write_text('{"lane_width_m":4}')
        await self.post('save',save,409)
        self.config.write_text('{"lane_width_m":3.2}')
        saved=await self.post('save',save)
        self.assertEqual(saved['project']['stages']['8'],self.doc['stages']['8'])
        self.assertNotIn('points',saved['project']['stages']['9']);self.assertNotIn('edges',saved['project']['stages']['9'])
        self.config.write_text('{"lane_width_m":4}')
        restored=await self.source();self.assertEqual(restored['saved']['lane_width_m'],3.2);self.assertEqual(restored['edges'],preview['edges'])
        self.assertEqual(restored['road_config']['lane_width_m'],4)
        await self.post('lane-preview',{**body,'source_digest':'stale'},409)
        rewound=await self.post('rewind',{'filename':'lane.json','revision':2,'stage':8})
        self.assertNotIn('9',rewound['project']['stages'])

    async def test_cancel_save_without_road_width_and_reload(self):
        source=await self.source()
        saved=await self.post('save',{'filename':'lane.json','source_digest':source['source_digest'],'stage':9,'revision':1,'enabled':False})
        self.assertEqual(saved['project']['stages']['9'],{'enabled':False,'source_digest':source['source_digest'],'reference_point':'gps_antenna','path_method':source['method']})
        restored=await self.source()
        self.assertIsNone(restored['edges'])
        self.assertFalse(restored['saved']['enabled'])
        rewound=await self.post('rewind',{'filename':'lane.json','revision':2,'stage':9})
        self.assertEqual(rewound['project']['stages']['9'],saved['project']['stages']['9'])
        self.assertEqual(restored['points'],lane_source(self.doc)['points'])

    async def test_vehicle_dimensions_and_gps_anchor_from_current_config(self):
        config={'vehicle_length_m':2.222,'vehicle_width_m':1.28,'rear_axle_distance_from_rear_m':.225,'gps_antenna_offset_x_m':.559,'gps_antenna_offset_y_m':0}
        with patch('dashboard.gps_path.vehicle_config',return_value=config):
            source=await self.source()
        self.assertEqual(source['vehicle'],config)
        self.assertIsNone(source['vehicle_error'])
        with patch('dashboard.gps_path.vehicle_config',return_value={**config,'vehicle_width_m':-1}):
            source=await self.source()
        self.assertIsNone(source['vehicle'])
        self.assertIn('vehicle_width_m',source['vehicle_error'])

    async def test_final_export_renames_working_file_and_omits_intermediate_data(self):
        source=await self.source()
        await self.post('save',{'filename':'lane.json','source_digest':source['source_digest'],'stage':9,'revision':1,'enabled':False})
        result=await self.post('export',{'filename':'lane.json','revision':2,'new_filename':'1단계_2026-09-26_120000_주행시험.json'})
        self.assertFalse(self.file.exists())
        working=Path(result['working']['path']);output=Path(result['export']['path'])
        self.assertTrue(working.is_file());self.assertEqual(output.parent,working.parent)
        self.assertTrue(working.name.startswith('13단계_'))
        self.assertIn('12',json.loads(working.read_text())['stages'])
        self.assertRegex(output.name,r'^MAP_\d{4}-\d{2}-\d{2}_\d{6,12}_주행시험.json$')
        final=json.loads(output.read_text());self.assertEqual(final['format'],'gps-final-map')
        self.assertNotIn('stages',final);self.assertNotIn('history',final);self.assertNotIn('matches',final)
        self.assertIn('9',json.loads(working.read_text())['stages'])
        self.assertEqual(final['points'],lane_source(self.doc)['points']);self.assertEqual(final['reference_point'],'gps_antenna');self.assertEqual(final['interpolation'],'piecewise_linear')
        self.assertFalse(final['lanes']['enabled'])
        again=await self.post('export',{'filename':working.name,'revision':3,'new_filename':working.name})
        self.assertNotEqual(again['export']['filename'],output.name)
        self.assertTrue(output.is_file())
        rewind=await self.post('rewind',{'filename':again['working']['filename'],'revision':again['working']['project']['revision'],'stage':11})
        self.assertIn('9',rewind['project']['stages'])

    async def test_export_collision_and_write_failure_keep_original(self):
        from dashboard.gps_project import write
        source=await self.source()
        self.config.write_text('{"lane_width_m":3.2}')
        preview=await self.post('lane-preview',{'filename':'lane.json','source_digest':source['source_digest']})
        await self.post('save',{'filename':'lane.json','revision':1,'stage':9,'source_digest':source['source_digest'],'road_digest':preview['settings']['road_digest']})
        before=self.file.read_bytes();other=self.file.with_name('occupied.json');other.write_text('do not overwrite')
        await self.post('export',{'filename':'lane.json','revision':2,'new_filename':other.name},409)
        self.assertEqual(other.read_text(),'do not overwrite');self.assertEqual(self.file.read_bytes(),before)
        def fail_final(name,*args,**kwargs):
            if name.startswith('MAP_'):raise web.HTTPInsufficientStorage()
            return write(name,*args,**kwargs)
        with patch('dashboard.gps_project.write',side_effect=fail_final):
            await self.post('export',{'filename':'lane.json','revision':2,'new_filename':'renamed.json'},507)
        self.assertEqual(self.file.read_bytes(),before);self.assertFalse(self.file.with_name('renamed.json').exists())
        result=await self.post('export',{'filename':'lane.json','revision':2,'new_filename':'lane.json'})
        final=json.loads(Path(result['export']['path']).read_text())
        self.assertEqual(final['lanes']['boundaries'],preview['edges'])
        self.assertEqual(final['lanes']['width_m'],3.2)

    async def test_stage_eight_ten_rename_and_eleven_suffix(self):
        source=await self.source()
        eight=await self.post('save',{'filename':'lane.json','revision':1,'stage':9,'enabled':False,'source_digest':source['source_digest'],'refresh_name':True})
        self.assertTrue(eight['filename'].startswith('9단계_'));self.assertFalse(self.file.exists())
        nine=await self.post('save',{'filename':eight['filename'],'revision':2,'stage':11,'bag':'2026-09-20_4','position_s':12.5,'validated_bags':['2026-09-20_4','2026-09-20_5'],'refresh_name':True})
        self.assertTrue(nine['filename'].startswith('12단계_'));self.assertFalse(Path(eight['path']).exists())
        self.assertEqual(nine['project']['stages']['11']['position_s'],12.5)
        reopened=json.loads(Path(nine['path']).read_text())
        self.assertEqual(reopened['stages']['11']['validated_bags'],['2026-09-20_4','2026-09-20_5'])
        ten=await self.post('export',{'filename':nine['filename'],'revision':3,'new_filename':nine['filename']})
        self.assertTrue(ten['working']['filename'].startswith('13단계_'))
        self.assertTrue(ten['export']['filename'].endswith('_lane.json'))
        self.assertFalse(Path(nine['path']).exists())
        eight_again=await self.post('save',{'filename':ten['working']['filename'],'revision':4,'stage':9,'retain':True,'refresh_name':True})
        self.assertTrue(eight_again['filename'].startswith('9단계_'))
        self.assertNotIn('12단계',eight_again['filename'])

    async def test_custom_width_preview_save_restore_and_export(self):
        from dashboard.gps_export import final_map
        self.config.write_text('{"lane_width_m":3.2}')
        source=await self.source();before=self.config.read_bytes()
        body={'filename':'lane.json','source_digest':source['source_digest'],'lane_width_m':4.5}
        preview=await self.post('lane-preview',body)
        self.assertEqual(preview['settings']['lane_width_m'],4.5)
        self.assertEqual(preview['settings']['road_config']['lane_width_m'],3.2)
        self.assertAlmostEqual(preview['edges']['left'][0]['n'],2.25)
        saved=await self.post('save',{**body,'stage':9,'revision':1,'road_digest':preview['settings']['road_digest']})
        self.assertEqual(saved['project']['stages']['9']['lane_width_m'],4.5)
        self.config.write_text('{"lane_width_m":3.8}')
        restored=await self.source()
        self.assertEqual(restored['saved']['lane_width_m'],4.5)
        self.assertEqual(restored['edges'],preview['edges'])
        final=final_map(saved['project'])
        self.assertEqual(final['lanes']['width_m'],4.5)
        self.assertEqual(final['lanes']['boundaries'],preview['edges'])
        for value in [0,-1,None,True,'5',float('nan')]:
            await self.post('lane-preview',{**body,'lane_width_m':value},400)
        self.config.write_bytes(before)
        await self.post('save',{**body,'stage':9,'revision':2,'lane_width_m':-1,'road_digest':preview['settings']['road_digest']},400)
        self.assertEqual(self.config.read_bytes(),before)

    async def test_old_curve_basis_cannot_be_retained_validated_or_exported(self):
        self.doc['stages'].update({'9':{'enabled':False,'source_digest':digest(self.doc['stages']['8'])},
                                  '10':{'sections':[{'name':'old curve section'}]},'11':{'validated_bags':['old-bag']}})
        self.file.write_text(json.dumps(self.doc));before=self.file.read_bytes()
        source=await self.source()
        self.assertIsNone(source['saved']);self.assertEqual(source['task_sections'],[])
        await self.post('save',{'filename':'lane.json','revision':1,'stage':9,'retain':True},409)
        await self.post('save',{'filename':'lane.json','revision':1,'stage':11,'validated_bags':['new-bag']},409)
        await self.post('export',{'filename':'lane.json','revision':1,'new_filename':'export.json'},409)
        self.assertEqual(self.file.read_bytes(),before)
        saved=await self.post('save',{'filename':'lane.json','revision':1,'stage':9,'enabled':False,'source_digest':source['source_digest']})
        self.assertNotIn('10',saved['project']['stages']);self.assertNotIn('11',saved['project']['stages'])
