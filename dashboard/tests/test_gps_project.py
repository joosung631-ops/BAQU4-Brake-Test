import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from dashboard.gps_project import add_routes
from dashboard.gps_review import identify

class ProjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_map_merge_placement_flows_through_noise_and_merging_with_original_preserved(self):
        from dashboard.gps_review import project as metric
        p=await self.post('create',{'filename':'placement.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True},map_merge=True)
        original=json.loads(json.dumps(p['project']['stages']['2']))
        clip={'id':'clip-example','bag':'comparison/b','start_seq':2,'end_seq':4,'offset_e':12.5,'offset_n':-8.,
              'points':[{'seq':i,'lat':37.+i*.00001,'lon':127.00002,'camera':{'file':'wrong.jpg'}} for i in range(2,5)]}
        p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[clip],refresh_name=True)
        self.assertTrue(p['filename'].startswith('3단계_'))
        self.assertEqual(p['project']['stages']['2'],original)
        result=p['project']['map_merge_result'];source=metric(clip['points'],self.raw['origin']);moved=metric(result['raw']['tracks'][-1]['points'],self.raw['origin'])
        for a,b in zip(source,moved):
            self.assertAlmostEqual(b['e']-a['e'],12.5,places=6);self.assertAlmostEqual(b['n']-a['n'],-8.,places=6)
        self.assertEqual([v['source_seq'] for v in moved],[2,3,4])
        self.assertTrue(all('camera' not in v for v in moved))
        self.assertEqual((await self.read(p['filename']))['project']['map_merge_result'],result)
        listing=await (await self.client.get('/api/gps/projects')).json();self.assertEqual(listing['files'][0]['last_stage'],2.5)
        editor=await (await self.client.get('/api/gps/projects/editor',params={'filename':p['filename'],'step':'points'})).json()
        self.assertEqual([len(t['points']) for t in editor['raw']['tracks']],[3])
        self.assertNotEqual(editor['review']['dataset_id'],self.dataset)
        await self.post('save',{'filename':p['filename'],'revision':p['project']['revision'],'stage':3,'dataset_id':self.dataset,'tracks':[]},409)
        specs=[{'id':t['id'],'excluded_seq':[]} for t in editor['review']['tracks']]
        preview=await self.post('preview',{'filename':p['filename'],'dataset_id':editor['review']['dataset_id'],'tracks':specs})
        self.assertEqual(len(preview['tracks']),1)
        p=await self.stage(p,3,dataset_id=editor['review']['dataset_id'],tracks=specs,refresh_name=True)
        self.assertTrue(p['filename'].startswith('4단계_'))
        # Saving the same placement preserves downstream work; moving it invalidates it.
        p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[clip]);self.assertIn('3',p['project']['stages'])
        additions=await (await self.client.get('/api/gps/projects/additions-source',params={'filename':p['filename']})).json()
        self.assertEqual([len(t['points']) for t in additions['tracks']],[3])
        merged=await (await self.client.get('/api/gps/projects/merge-source',params={'filename':p['filename']})).json()
        p=await self.stage(p,5,source_digest=merged['source_digest'],tracks=[{'id':t['id'],'groups':[[v['seq']] for v in t['points']]} for t in merged['source']['tracks']])
        self.assertEqual(sum(len(t['points']) for t in p['project']['stages']['5']['tracks']),3)
        p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[{**clip,'offset_e':20.}])
        self.assertNotIn('3',p['project']['stages']);self.assertNotIn('5',p['project']['stages'])
        self.assertEqual(p['project']['stages']['2'],original)
        p=await self.post('rewind',{'filename':p['filename'],'revision':p['project']['revision'],'stage':2.5})
        self.assertIn('map_merge_result',p['project'])
        p=await self.post('rewind',{'filename':p['filename'],'revision':p['project']['revision'],'stage':2})
        self.assertNotIn('map_merge_result',p['project'])
        editor=await (await self.client.get('/api/gps/projects/editor',params={'filename':p['filename'],'step':'points'})).json()
        self.assertEqual(editor['raw']['tracks'],[])
        bags=await (await self.client.get('/api/gps/projects/editor',params={'filename':p['filename'],'step':'bags'})).json()
        self.assertEqual(bags['raw'],self.raw)

    async def test_map_merge_rotation_preserves_center_and_distances_and_feeds_next_stage(self):
        import math
        from dashboard.gps_review import project as metric
        p=await self.post('create',{'filename':'rotation.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True},map_merge=True)
        clip={'id':'clip-rotate','bag':'b','start_seq':1,'end_seq':3,'offset_e':11.,'offset_n':-7.,'rotation_deg':90.,
              'points':[{'seq':1,'lat':37.,'lon':127.},{'seq':2,'lat':37.00001,'lon':127.00002},{'seq':3,'lat':37.00003,'lon':127.00001}]}
        base=metric(clip['points'],self.raw['origin']);ce=(min(p['e'] for p in base)+max(p['e'] for p in base))/2;cn=(min(p['n'] for p in base)+max(p['n'] for p in base))/2
        for angle in [90.,-45.,180.,450.]:
            p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[{**clip,'rotation_deg':angle}])
            saved=p['project']['map_merge_result'];points=metric(saved['raw']['tracks'][-1]['points'],self.raw['origin']);r=math.radians(angle)
            for a,b in zip(base,points):
                e,n=a['e']-ce,a['n']-cn
                self.assertAlmostEqual(b['e'],ce+math.cos(r)*e-math.sin(r)*n+11.,places=6)
                self.assertAlmostEqual(b['n'],cn+math.sin(r)*e+math.cos(r)*n-7.,places=6)
            for i in range(len(points)-1):self.assertAlmostEqual(math.hypot(points[i+1]['e']-points[i]['e'],points[i+1]['n']-points[i]['n']),math.hypot(base[i+1]['e']-base[i]['e'],base[i+1]['n']-base[i]['n']),places=6)
            self.assertEqual(p['project']['stages']['2']['raw'],self.raw)
        self.assertEqual((await self.read(p['filename']))['project']['map_merge_result']['clips'][0]['rotation_deg'],90.)
        editor=await (await self.client.get('/api/gps/projects/editor',params={'filename':p['filename'],'step':'points'})).json()
        self.assertEqual(editor['raw'],saved['raw'])
        specs=[{'id':t['id'],'excluded_seq':[]} for t in editor['review']['tracks']]
        p=await self.stage(p,3,dataset_id=editor['review']['dataset_id'],tracks=specs)
        self.assertIn('3',p['project']['stages'])
        p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[{**clip,'rotation_deg':-90.}])
        self.assertNotIn('3',p['project']['stages'])
        baseline=(self.root/'review/maps'/p['filename']).read_bytes()
        for angle in [None,'90',True,float('nan'),float('inf')]:
            await self.post('save',{'filename':p['filename'],'revision':p['project']['revision'],'stage':'map-merge','source_dataset_id':self.dataset,'clips':[{**clip,'rotation_deg':angle}]},400)
            self.assertEqual((self.root/'review/maps'/p['filename']).read_bytes(),baseline)
        # Earlier saved clips omit the rotation field and keep their translated coordinates.
        clip.pop('rotation_deg')
        p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[clip])
        points=metric(p['project']['map_merge_result']['raw']['tracks'][-1]['points'],self.raw['origin'])
        self.assertEqual(p['project']['map_merge_result']['clips'][0]['rotation_deg'],0.)
        for a,b in zip(base,points):self.assertAlmostEqual(b['e']-a['e'],11.,places=6);self.assertAlmostEqual(b['n']-a['n'],-7.,places=6)

    async def test_invalid_and_stale_map_merge_placements_do_not_change_file(self):
        p=await self.post('create',{'filename':'invalid-placement.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True},map_merge=True)
        clip={'id':'clip-a','bag':'b','start_seq':1,'end_seq':2,'offset_e':0.,'offset_n':0.,'points':[{'seq':i,'lat':37.+i*.00001,'lon':127.} for i in (1,2)]}
        baseline=(self.root/'review/maps'/p['filename']).read_bytes()
        invalid=[None,[{}],[{**clip,'points':clip['points'][:1]}],[{**clip,'offset_e':float('nan')}],[{**clip,'offset_e':1e300}],[{**clip,'start_seq':2}],
                 [{**clip,'points':[clip['points'][1],clip['points'][0]]}],[clip,clip],[{**clip,'points':[clip['points'][0],{**clip['points'][1],'lat':91}]}]]
        for clips in invalid:
            await self.post('save',{'filename':p['filename'],'revision':p['project']['revision'],'stage':'map-merge','source_dataset_id':self.dataset,'clips':clips},400)
            self.assertEqual((self.root/'review/maps'/p['filename']).read_bytes(),baseline)
        for patch in [{'source_dataset_id':'stale'},{'revision':99}]:
            await self.post('save',{'filename':p['filename'],'revision':p['project']['revision'],'stage':'map-merge','source_dataset_id':self.dataset,'clips':[clip],**patch},409)
        self.assertEqual((self.root/'review/maps'/p['filename']).read_bytes(),baseline)
        p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[clip])
        # Disabling merging removes its effective input and any dependent noise output.
        p=await self.stage(p,2,dataset_id=self.dataset,use_saved=True,display={'linear':True,'smooth':True},map_merge=False)
        self.assertNotIn('map_merge_result',p['project'])

    async def test_reference_is_excluded_from_fusion_ordering_path_and_final_export(self):
        from test_gps_path import VEHICLE
        from dashboard.gps_export import final_map
        from dashboard.gps_review import project as metric
        vehicle=self.root/'vehicle.json';vehicle.write_text(json.dumps(VEHICLE))
        road=self.root/'road.json';road.write_text('{"lane_width_m":3.2}')
        with patch.dict(os.environ,{'DASHBOARD_VEHICLE_CONFIG':str(vehicle),'DASHBOARD_ROAD_CONFIG':str(road)}):
            p=await self.post('create',{'filename':'background-final.json'})
            p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True},map_merge=True)
            clip={'id':'clip-final','bag':'b','start_seq':1,'end_seq':4,'offset_e':80.,'offset_n':0.,'points':self.raw['tracks'][0]['points']}
            p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[clip])
            editor=await (await self.client.get('/api/gps/projects/editor',params={'filename':p['filename'],'step':'points'})).json()
            self.assertEqual(len(editor['raw']['tracks']),1)
            p=await self.stage(p,3,dataset_id=editor['review']['dataset_id'],tracks=[{'id':t['id'],'excluded_seq':[]} for t in editor['review']['tracks']])
            merged=await (await self.client.get('/api/gps/projects/merge-source',params={'filename':p['filename']})).json()
            p=await self.stage(p,5,source_digest=merged['source_digest'],tracks=[{'id':t['id'],'groups':[[v['seq']] for v in t['points']]} for t in merged['source']['tracks']])
            fusion=await (await self.client.get('/api/gps/projects/fusion-source',params={'filename':p['filename']})).json()
            self.assertEqual(len(fusion['points']),4)
            p=await self.stage(p,6,source_digest=fusion['source_digest'],groups=[[v['id']] for v in fusion['points']],radius_m=.5)
            order=await (await self.client.get('/api/gps/projects/order-source',params={'filename':p['filename']})).json()
            self.assertEqual(len(order['references']),1)
            ordered=await self.post('order-auto',{'filename':p['filename'],'source_digest':order['source_digest'],'reference_id':order['references'][0]['id'],'max_distance_m':2.})
            p=await self.stage(p,7,source_digest=order['source_digest'],reference_id=ordered['reference_id'],max_distance_m=2.,order=ordered['auto_order'])
            path=await (await self.client.get('/api/gps/projects/path-source',params={'filename':p['filename']})).json()
            p=await self.stage(p,8,source_digest=path['source_digest'],draft=True,waypoints=path['waypoints'],settings={'max_deviation_m':.2,'smoothing':1})
            lane=await (await self.client.get('/api/gps/projects/lane-source',params={'filename':p['filename']})).json()
            preview=await self.post('lane-preview',{'filename':p['filename'],'source_digest':lane['source_digest'],'lane_width_m':3.2})
            p=await self.stage(p,9,source_digest=lane['source_digest'],road_digest=preview['settings']['road_digest'],lane_width_m=3.2)
            final=final_map(p['project'])
            self.assertGreater(len(final['points']),2)
            self.assertTrue(all(v['e']>79.9 for v in final['points']))
            self.assertTrue(all(abs(v['e'])<1e-6 for v in metric(self.raw['tracks'][0]['points'],self.raw['origin'])))
            self.assertEqual(p['project']['stages']['2']['raw'],self.raw)

    async def test_legacy_combined_reference_projects_migrate_without_overwriting_source_file(self):
        from dashboard.gps_project import review
        p=await self.post('create',{'filename':'legacy-combined.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True},map_merge=True)
        clip={'id':'clip-legacy','bag':'b','start_seq':1,'end_seq':4,'offset_e':5.,'offset_n':0.,'rotation_deg':30.,'points':self.raw['tracks'][0]['points']}
        p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[clip])
        doc=p['project'];combined=doc['map_merge_result'];combined.pop('version')
        combined['raw']['tracks']=self.raw['tracks']+combined['raw']['tracks'];combined['raw']['selected_bags']=['a']
        combined['dataset_id']=identify(combined['raw'])[1]
        doc['stages']['3']=review(combined['raw']);doc['stages']['8']={'draft':True}
        path=self.root/'review/maps'/p['filename'];path.write_text(json.dumps(doc));before=path.read_bytes()
        restored=await self.read(p['filename']);current=restored['project']
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(current['stages']['2']['raw'],self.raw)
        self.assertEqual(current['map_merge_result']['version'],2)
        self.assertEqual(len(current['map_merge_result']['raw']['tracks']),1)
        self.assertEqual(current['map_merge_result']['clips'],combined['clips'])
        self.assertNotIn('3',current['stages']);self.assertNotIn('8',current['stages'])
        self.assertIn('3',current['history'][-1]['stages']);self.assertIn('8',current['history'][-1]['stages'])
        self.assertIn('배경 전용',current['history'][-1]['reason'])
        # First subsequent save persists the migration, and another load does not repeat it.
        p=await self.stage(restored,'map-merge',source_dataset_id=self.dataset,clips=[clip])
        self.assertEqual(len((await self.read(p['filename']))['project']['history']),1)

    async def test_optional_map_merge_persists_without_changing_gps_stage_keys(self):
        p=await self.post('create',{'filename':'merge-option.json'})
        settings={'dataset_id':self.dataset,'display':{'linear':True,'smooth':True}}
        p=await self.stage(p,2,**settings)
        self.assertIs(p['project']['stages']['2']['map_merge'],False)
        p=await self.stage(p,2,map_merge=True,**settings)
        self.assertIs((await self.read(p['filename']))['project']['stages']['2']['map_merge'],True)
        await self.post('save',{'filename':p['filename'],'revision':p['project']['revision'],'stage':3,'dataset_id':self.dataset,'tracks':[]},409)
        clip={'id':'clip-option','bag':'b','start_seq':1,'end_seq':4,'offset_e':0.,'offset_n':0.,'points':self.raw['tracks'][0]['points']}
        p=await self.stage(p,'map-merge',source_dataset_id=self.dataset,clips=[clip])
        active,dataset=identify(p['project']['map_merge_result']['raw'])
        p=await self.stage(p,3,dataset_id=dataset,tracks=[{'id':active[0]['id'],'excluded_seq':[2]}],refresh_name=True)
        self.assertTrue(p['filename'].startswith('4단계_'))
        self.assertEqual(p['project']['stages']['3']['tracks'][0]['excluded_seq'],[2])
        files=await (await self.client.get('/api/gps/projects')).json()
        self.assertEqual(files['files'][0]['last_stage'],3)
        self.assertIs(files['files'][0]['map_merge'],True)
        clone=await self.post('create',{'filename':'merge-copy.json','source':p['filename']})
        self.assertIs(clone['project']['stages']['2']['map_merge'],True)
        # Requests from older clients retain the selected option.
        p=await self.stage(p,2,use_saved=True,**settings)
        self.assertIs(p['project']['stages']['2']['map_merge'],True)
        self.assertIn('3',p['project']['stages'])
        baseline=(self.root/'review/maps'/p['filename']).read_bytes()
        await self.post('save',{'filename':p['filename'],'revision':p['project']['revision'],'stage':2,'map_merge':'true',**settings},400)
        self.assertEqual((self.root/'review/maps'/p['filename']).read_bytes(),baseline)
        p=await self.stage(p,2,map_merge=False,use_saved=True,**settings)
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=[{'id':self.tracks[0]['id'],'excluded_seq':[2]}],refresh_name=True)
        self.assertTrue(p['filename'].startswith('3단계_'))

    async def test_manual_additions_survive_reload_feed_merging_and_invalidate_downstream(self):
        p=await self.post('create',{'filename':'manual.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True})
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=[{'id':self.tracks[0]['id'],'excluded_seq':[2]}])
        source=await (await self.client.get('/api/gps/projects/additions-source',params={'filename':p['filename']})).json()
        key=source['tracks'][0]['id']
        additions=[{'id':'manual-a','track_id':key,'after':'raw:1','lat':37.00002,'lon':127.00001},
                   {'id':'manual-b','track_id':key,'after':'manual-a','lat':37.000025,'lon':127.00001}]
        p=await self.stage(p,4,source_digest=source['source_digest'],additions=additions)
        restored=await self.read(p['filename'])
        self.assertEqual(restored['project']['stages']['4']['additions'],additions)
        self.assertEqual(restored['project']['stages']['2']['raw'],self.raw)
        merged=await (await self.client.get('/api/gps/projects/merge-source',params={'filename':p['filename']})).json()
        points=merged['source']['tracks'][0]['points']
        self.assertEqual([v['source_seq'] for v in points],[1,None,None,3,4])
        self.assertEqual([v['seq'] for v in points],[1,2,3,4,5])
        p=await self.stage(p,5,source_digest=merged['source_digest'],tracks=[{'id':key,'groups':[[v['seq']] for v in points]}])
        fused=await (await self.client.get('/api/gps/projects/fusion-source',params={'filename':p['filename']})).json()
        p=await self.stage(p,6,source_digest=fused['source_digest'],groups=[[v['id']] for v in fused['points']],radius_m=.5)
        ordered=await (await self.client.get('/api/gps/projects/order-source',params={'filename':p['filename']})).json()
        self.assertEqual(ordered['references'][0]['point_count'],5)
        self.assertEqual(len(ordered['points']),5)
        p=await self.stage(p,4,source_digest=source['source_digest'],additions=[])
        self.assertNotIn('5',p['project']['stages']);self.assertNotIn('6',p['project']['stages'])
        self.assertIn('5',p['project']['history'][-1]['stages'])
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=[{'id':key,'excluded_seq':[3]}])
        self.assertNotIn('4',p['project']['stages'])

    async def test_invalid_or_stale_manual_additions_cannot_change_saved_project(self):
        p=await self.post('create',{'filename':'invalid-manual.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True})
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=[{'id':self.tracks[0]['id'],'excluded_seq':[]}])
        source=await (await self.client.get('/api/gps/projects/additions-source',params={'filename':p['filename']})).json()
        valid={'id':'manual-a','track_id':self.tracks[0]['id'],'after':'raw:1','lat':37.,'lon':127.}
        baseline=(self.root/'review/maps'/p['filename']).read_bytes()
        for items in [[{**valid,'lat':91}],[{**valid,'lon':float('nan')}],[{**valid,'after':'missing'}],[{**valid,'track_id':'missing'}],[valid,valid]]:
            await self.post('save',{'filename':p['filename'],'revision':p['project']['revision'],'stage':4,'source_digest':source['source_digest'],'additions':items},400)
            self.assertEqual((self.root/'review/maps'/p['filename']).read_bytes(),baseline)
        await self.post('save',{'filename':p['filename'],'revision':p['project']['revision'],'stage':4,'source_digest':'stale','additions':[valid]},409)
        self.assertEqual((self.root/'review/maps'/p['filename']).read_bytes(),baseline)

    async def test_version_two_projects_shift_stages_in_memory_without_touching_saved_file(self):
        path=self.root/'review/maps/old-version.json';path.parent.mkdir(parents=True,exist_ok=True)
        old={'format':'gps-map-project','version':2,'revision':1,'stages':{'1':{},'4':{'tracks':[]},'8':{'enabled':False},'11':{'export_filename':'MAP_old.json'}},
             'history':[{'stages':{'4':{'tracks':[]},'10':{'validated_bags':['old']}}}]}
        path.write_text(json.dumps(old));before=path.read_bytes()
        loaded=await self.read(path.name)
        self.assertEqual(loaded['project']['version'],3)
        self.assertEqual(set(loaded['project']['stages']),{'1','5','9','12'})
        self.assertEqual(set(loaded['project']['history'][0]['stages']),{'5','11'})
        self.assertEqual(path.read_bytes(),before)

    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'DASHBOARD_GPS_MAP_DIR':str(self.root),'DASHBOARD_GPS_REVIEW_DIR':str(self.root/'review')});self.env.start()
        (self.root/'test').mkdir();self.raw={'format':'gps-test-raw','version':1,'origin':[37,127],'selected_bags':['a'],'tracks':[{'name':'a','points':[{'seq':i,'lat':37+i*.00001,'lon':127} for i in range(1,5)]}]}
        (self.root/'test/raw.json').write_text(json.dumps(self.raw));self.tracks,self.dataset=identify(self.raw)
        app=web.Application();add_routes(app);self.client=TestClient(TestServer(app));await self.client.start_server()
    async def asyncTearDown(self):await self.client.close();self.env.stop();self.tmp.cleanup()
    async def post(self,path,body,status=200):
        r=await self.client.post('/api/gps/projects/'+path,json=body,headers={'X-Dashboard-Control':'1'});self.assertEqual(r.status,status,await r.text());return await r.json() if status==200 else None
    async def read(self,name):return await (await self.client.get('/api/gps/projects/load',params={'filename':name})).json()
    async def stage(self,p,stage,**kwargs):return await self.post('save',dict(filename=p['filename'],revision=p['project']['revision'],stage=stage,**kwargs))
    async def test_single_file_copy_resume_conflict_and_invalidation(self):
        p=await self.post('create',{'filename':'맵_원본.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,bags=['a'],display={'linear':True,'smooth':True})
        spec={'id':self.tracks[0]['id'],'excluded_seq':[2]}
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=[spec])
        source=await (await self.client.get('/api/gps/projects/merge-source',params={'filename':p['filename']})).json()
        p=await self.stage(p,5,source_digest=source['source_digest'],tracks=[{'id':spec['id'],'groups':[[1,3],[4]]}])
        self.assertEqual(set(p['project']['stages']),{'1','2','3','5'})
        self.assertEqual(len(list((self.root/'review/maps').glob('*.json'))),1)
        self.assertEqual(p['project']['stages']['5']['tracks'][0]['points'][0]['source_seqs'],[1,3])
        before=(self.root/'review/maps/맵_원본.json').read_bytes()
        clone=await self.post('create',{'filename':'맵_수정.json','source':'맵_원본.json'})
        await self.post('create',{'filename':'맵_원본.json'},409)
        await self.post('save',{'filename':'맵_수정.json','revision':99,'stage':3,'tracks':[spec]},409)
        clone=await self.stage(clone,3,dataset_id=self.dataset,tracks=[{'id':spec['id'],'excluded_seq':[]}])
        self.assertNotIn('5',clone['project']['stages']);self.assertIn('5',clone['project']['history'][0]['stages'])
        self.assertEqual((self.root/'review/maps/맵_원본.json').read_bytes(),before)
        # Project sources survive global bag changes and reopening.
        (self.root/'test/raw.json').unlink()
        editor=await (await self.client.get('/api/gps/projects/editor',params={'filename':'맵_원본.json','step':'points'})).json()
        self.assertEqual(editor['review']['tracks'][0]['excluded_seq'],[2]);self.assertEqual(editor['raw'],self.raw)
        self.assertEqual((await self.read('맵_수정.json'))['project'],clone['project'])
        p=await self.stage(p,2,use_saved=True,dataset_id=self.dataset,bags=['a'],display={'linear':False,'smooth':True})
        self.assertIn('5',p['project']['stages'])
    async def test_validation_and_changed_sources(self):
        p=await self.post('create',{'filename':'new.json'})
        await self.post('create',{'filename':'../outside.json'},400)
        await self.post('save',{'filename':'new.json','revision':1,'stage':3,'tracks':[]},409)
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True})
        await self.post('save',{'filename':'new.json','revision':2,'stage':3,'dataset_id':self.dataset},400)
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=[{'id':self.tracks[0]['id'],'excluded_seq':[]}])
        self.raw['tracks'][0]['points'][0]['lat']+=.01;(self.root/'test/raw.json').write_text(json.dumps(self.raw))
        _,new_dataset=identify(self.raw)
        p=await self.stage(p,2,dataset_id=new_dataset,display={'linear':True,'smooth':True})
        self.assertNotIn('3',p['project']['stages']);self.assertIn('3',p['project']['history'][0]['stages'])

    async def test_import_previous_review_without_changing_original(self):
        from dashboard.gps_review import build_review
        saved={'tracks':{self.tracks[0]['id']:build_review(self.tracks[0],self.raw['origin'],[2],.5,start_seq=1,end_seq=3)}}
        (self.root/'review').mkdir();path=self.root/'review/review.json';path.write_text(json.dumps(saved));before=path.read_bytes()
        p=await self.post('create',{'filename':'imported.json','source':'review.json','kind':'review'})
        self.assertEqual(p['project']['stages']['3']['tracks'][0]['excluded_seq'],[2,4])
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(p['project']['stages']['2']['raw'],self.raw)

    async def test_rewind_removes_downstream_and_history_with_revision_guard(self):
        p=await self.post('create',{'filename':'rewind.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True})
        specs=[{'id':self.tracks[0]['id'],'excluded_seq':[]}]
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=specs)
        source=await (await self.client.get('/api/gps/projects/merge-source',params={'filename':'rewind.json'})).json()
        p=await self.stage(p,5,source_digest=source['source_digest'],tracks=[{'id':specs[0]['id'],'groups':[[1,2],[3,4]]}])
        specs[0]['excluded_seq']=[2]
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=specs)
        self.assertIn('5',p['project']['history'][0]['stages'])
        before=await self.read('rewind.json')
        await self.post('rewind',{'filename':'rewind.json','revision':0,'stage':2},409)
        self.assertEqual(await self.read('rewind.json'),before)
        p=await self.post('rewind',{'filename':'rewind.json','revision':p['project']['revision'],'stage':2})
        self.assertEqual(set(p['project']['stages']),{'1','2'});self.assertNotIn('history',p['project'])
        self.assertEqual(p['project']['stages']['2'],before['project']['stages']['2'])
        p=await self.post('rewind',{'filename':'rewind.json','revision':p['project']['revision'],'stage':1})
        self.assertEqual(set(p['project']['stages']),{'1'})

    async def test_resume_rotates_filename_preserves_suffix_and_revision(self):
        name='1단계_2026-01-01_010203_사용자_문구.json'
        p=await self.post('create',{'filename':name})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True})
        original=(self.root/'review/maps'/name).read_bytes()
        await self.post('resume',{'filename':name,'revision':0},409)
        self.assertEqual((self.root/'review/maps'/name).read_bytes(),original)
        with patch('dashboard.gps_project.write',side_effect=OSError('disk full')):
            r=await self.client.post('/api/gps/projects/resume',json={'filename':name,'revision':p['project']['revision']},headers={'X-Dashboard-Control':'1'})
            self.assertEqual(r.status,500)
        self.assertEqual((self.root/'review/maps'/name).read_bytes(),original)
        resumed=await self.post('resume',{'filename':name,'revision':p['project']['revision']})
        self.assertRegex(resumed['filename'],r'^2단계_\d{4}-\d{2}-\d{2}_\d{6,12}_사용자_문구.json$')
        self.assertFalse((self.root/'review/maps'/name).exists())
        self.assertEqual(resumed['project']['stages'],p['project']['stages'])
        later=await self.stage(resumed,3,dataset_id=self.dataset,tracks=[{'id':self.tracks[0]['id'],'excluded_seq':[]}],refresh_name=True)
        self.assertTrue(later['filename'].startswith('3단계_'));self.assertTrue(later['filename'].endswith('_사용자_문구.json'))
        self.assertFalse((self.root/'review/maps'/resumed['filename']).exists())
        rewind=await self.post('rewind',{'filename':later['filename'],'revision':later['project']['revision'],'stage':2,'refresh_name':True})
        self.assertTrue(rewind['filename'].startswith('2단계_'));self.assertEqual(set(rewind['project']['stages']),{'1','2'})
        self.assertEqual(len(list((self.root/'review/maps').glob('*.json'))),1)

    async def test_merge_preview_uses_current_groups_without_writing(self):
        p=await self.post('create',{'filename':'curves.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True})
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=[{'id':self.tracks[0]['id'],'excluded_seq':[]}])
        src=await (await self.client.get('/api/gps/projects/merge-source',params={'filename':'curves.json'})).json()
        before=(self.root/'review/maps/curves.json').read_bytes()
        result=await self.post('merge-preview',{'filename':'curves.json','source_digest':src['source_digest'],'tracks':[{'id':self.tracks[0]['id'],'groups':[[1,2,3,4]]}]})
        curve=result['tracks'][0]['curve_segments'];self.assertEqual(len(curve),1);self.assertEqual(len(curve[0]),1)
        self.assertAlmostEqual(curve[0][0]['n'],2.782987,places=5)
        self.assertEqual((self.root/'review/maps/curves.json').read_bytes(),before)
        from dashboard.gps_project import merge_curves
        source={'origin':[37,127],'tracks':[{'id':'a','name':'a','points':[{'seq':i,'lat':37+i*.00001,'lon':127,'segment':int(i>2)} for i in range(1,5)]}]}
        result=merge_curves(source,[{'id':'a','groups':[[1],[2],[3],[4]]}])
        self.assertEqual(len(result[0]['curve_segments']),2)

    async def test_stage5_roundtrip_auto_and_rewind(self):
        p=await self.post('create',{'filename':'fusion.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True})
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=[{'id':self.tracks[0]['id'],'excluded_seq':[]}])
        src=await (await self.client.get('/api/gps/projects/merge-source',params={'filename':'fusion.json'})).json()
        p=await self.stage(p,5,source_digest=src['source_digest'],tracks=[{'id':self.tracks[0]['id'],'groups':[[1],[2],[3],[4]]}])
        src=await (await self.client.get('/api/gps/projects/fusion-source',params={'filename':'fusion.json'})).json()
        groups=[[pt['id']] for pt in src['points']]
        before=(self.root/'review/maps/fusion.json').read_bytes()
        auto=await self.post('fusion-auto',{'filename':'fusion.json','source_digest':src['source_digest'],'groups':groups,'selected':[0,1],'radius_m':2})
        self.assertEqual(len(auto['groups']),3);self.assertEqual((self.root/'review/maps/fusion.json').read_bytes(),before)
        p=await self.stage(p,6,source_digest=src['source_digest'],groups=auto['groups'],radius_m=2)
        self.assertEqual(len(p['project']['stages']['6']['points']),3)
        loaded=await (await self.client.get('/api/gps/projects/fusion-source',params={'filename':'fusion.json'})).json()
        self.assertEqual(loaded['saved']['groups'],auto['groups'])
        await self.post('save',{'filename':'fusion.json','revision':p['project']['revision'],'stage':6,'source_digest':'stale','groups':groups},409)
        p=await self.post('rewind',{'filename':'fusion.json','revision':p['project']['revision'],'stage':5})
        self.assertIn('5',p['project']['stages']);self.assertNotIn('6',p['project']['stages'])

    async def test_stage6_order_roundtrip_and_rewind(self):
        p=await self.post('create',{'filename':'ordering.json'})
        p=await self.stage(p,2,dataset_id=self.dataset,display={'linear':True,'smooth':True})
        p=await self.stage(p,3,dataset_id=self.dataset,tracks=[{'id':self.tracks[0]['id'],'excluded_seq':[]}])
        src=await (await self.client.get('/api/gps/projects/merge-source',params={'filename':p['filename']})).json()
        p=await self.stage(p,5,source_digest=src['source_digest'],tracks=[{'id':self.tracks[0]['id'],'groups':[[1],[2],[3],[4]]}])
        src=await (await self.client.get('/api/gps/projects/fusion-source',params={'filename':p['filename']})).json()
        p=await self.stage(p,6,source_digest=src['source_digest'],groups=[[v['id']] for v in src['points']],radius_m=.5)
        src=await (await self.client.get('/api/gps/projects/order-source',params={'filename':p['filename']})).json()
        before=(self.root/'review/maps/ordering.json').read_bytes()
        auto=await self.post('order-auto',{'filename':p['filename'],'source_digest':src['source_digest'],'reference_id':self.tracks[0]['id'],'max_distance_m':1})
        self.assertEqual(auto['auto_order'],[0,1,2,3]);self.assertEqual((self.root/'review/maps/ordering.json').read_bytes(),before)
        p=await self.stage(p,7,source_digest=src['source_digest'],reference_id=self.tracks[0]['id'],max_distance_m=1,order=[3,0,1,2])
        saved=(await (await self.client.get('/api/gps/projects/order-source',params={'filename':p['filename']})).json())['saved']
        self.assertEqual(saved['order'],[3,0,1,2]);self.assertEqual(saved['ordered_points'][0]['index'],1)
        await self.post('save',{'filename':p['filename'],'revision':p['project']['revision'],'stage':7,'source_digest':'stale'},409)
        p=await self.post('rewind',{'filename':p['filename'],'revision':p['project']['revision'],'stage':6})
        self.assertIn('6',p['project']['stages']);self.assertNotIn('7',p['project']['stages'])

    async def test_numbered_saves_preserve_actual_extraction_bags(self):
        p=await self.post('create',{'filename':'1단계_2026-01-01_120000_문구.json'})
        old=p['path']
        p=await self.stage(p,2,dataset_id=self.dataset,bags=['incorrect-client-value'],display={'linear':True,'smooth':True},refresh_name=True)
        self.assertTrue(p['filename'].startswith('2단계_'));self.assertTrue(p['filename'].endswith('_문구.json'));self.assertFalse(Path(old).exists())
        saved=await self.read(p['filename']);self.assertEqual(saved['project']['stages']['2']['bags'],['a'])
        old=p['path'];p=await self.stage(p,3,dataset_id=self.dataset,tracks=[{'id':self.tracks[0]['id'],'excluded_seq':[]}],refresh_name=True)
        self.assertTrue(p['filename'].startswith('3단계_'));self.assertFalse(Path(old).exists())
        source=await (await self.client.get('/api/gps/projects/merge-source',params={'filename':p['filename']})).json()
        old=p['path'];p=await self.stage(p,5,source_digest=source['source_digest'],tracks=[{'id':self.tracks[0]['id'],'groups':[[1,2],[3,4]]}],refresh_name=True)
        self.assertTrue(p['filename'].startswith('5단계_'));self.assertFalse(Path(old).exists())
        self.assertEqual(p['project']['stages']['2']['bags'],['a'])
