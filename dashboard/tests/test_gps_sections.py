import copy
import json
import math
import unittest
from pathlib import Path
from aiohttp import web
from dashboard.gps_lane import lane_settings
from dashboard.gps_sections import section_source, section_result
from dashboard.gps_project import load
from dashboard.gps_export import final_map
import test_gps_lane


class SectionApiTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = test_gps_lane.LaneApiTests.asyncTearDown
    post = test_gps_lane.LaneApiTests.post
    async def asyncSetUp(self):
        await test_gps_lane.LaneApiTests.asyncSetUp(self)
        self.doc['version']=3
        self.doc['stages']['9']=lane_settings(self.doc,{'lane_width_m':3.2})
        self.file.write_text(json.dumps(self.doc))

    async def test_sections_roundtrip_export_and_invalidation(self):
        source=section_source(self.doc)
        specs=[{'name':'신호 구간','description':'정지선부터 교차로 종료까지',
                'start':{'segment_index':20,'fraction':0.},'end':{'segment_index':80,'fraction':0.}}]
        saved=await self.post('save',{'filename':'lane.json','revision':1,'stage':10,'source_digest':source['source_digest'],'sections':specs,'refresh_name':True})
        self.assertTrue(saved['filename'].startswith('10단계_'))
        section=saved['project']['stages']['10']['sections'][0]
        self.assertAlmostEqual(section['start']['s_m'],2)
        self.assertAlmostEqual(section['end']['left']['e'],8.);self.assertAlmostEqual(section['end']['left']['n'],1.6)
        self.assertEqual(final_map(saved['project'])['task_sections'],[section])
        restored=await (await self.client.get('/api/gps/projects/section-source',params={'filename':saved['filename']})).json()
        self.assertEqual(restored['saved']['sections'],[section])
        verified=await self.post('save',{'filename':saved['filename'],'revision':2,'stage':11,'validated_bags':['bag4']})
        self.assertIn('11',verified['project']['stages'])
        changed=await self.post('save',{'filename':saved['filename'],'revision':3,'stage':10,'source_digest':source['source_digest'],'sections':[]})
        self.assertNotIn('11',changed['project']['stages'])
        self.assertEqual(final_map(changed['project'])['task_sections'],[])

    async def test_invalid_sections_and_stale_lane_do_not_write(self):
        source=section_source(self.doc)
        good={'name':'test','description':'description','start':{'segment_index':20,'fraction':0.},'end':{'segment_index':80,'fraction':0.}}
        before=self.file.read_bytes()
        for replacement in [{'name':''},{'description':' '},{'end':good['start']},{'end':{'segment_index':0,'fraction':.1}},{'start':{'segment_index':9999,'fraction':0}},{'start':{'segment_index':0,'fraction':float('nan')}}]:
            await self.post('save',{'filename':'lane.json','revision':1,'stage':10,'source_digest':source['source_digest'],'sections':[{**good,**replacement}]},400)
        await self.post('save',{'filename':'lane.json','revision':1,'stage':10,'source_digest':'stale','sections':[good]},409)
        self.assertEqual(before,self.file.read_bytes())

    async def test_migration_preserves_old_validation_export_and_history(self):
        self.doc['version']=1
        self.doc['stages']={str(int(k)-1) if int(k)>=5 else k:v for k,v in self.doc['stages'].items()}
        old={'9':{'validated_bags':['bag4'],'source_digest':'old'},'10':{'export_filename':'MAP_old.json'}}
        self.doc['stages'].update(copy.deepcopy(old));self.doc['history']=[{'stages':copy.deepcopy(old)}]
        self.file.write_text(json.dumps(self.doc));before=self.file.read_bytes()
        migrated=load('lane.json')
        self.assertEqual(migrated['version'],3)
        for stages in [migrated['stages'],migrated['history'][0]['stages']]:
            self.assertNotIn('10',stages);self.assertEqual(stages['11'],old['9']);self.assertEqual(stages['12'],old['10'])
        self.assertEqual(before,self.file.read_bytes())
        self.file.write_text(json.dumps(migrated))
        self.assertEqual(load('lane.json'),migrated)
        rewind=await self.post('rewind',{'filename':'lane.json','revision':1,'stage':10})
        self.assertNotIn('11',rewind['project']['stages']);self.assertNotIn('12',rewind['project']['stages'])
        self.assertNotIn('history',rewind['project'])

    async def test_corner_boundary_uses_linear_source_and_saved_lane_edges(self):
        from test_gps_path import document
        from dashboard.gps_review import digest
        from dashboard.gps_lane import lane_edges
        doc=document([[0,0],[5,0],[5,5]])
        doc['stages']['8']={'draft':True,'valid':False,'source_digest':digest(doc['stages']['7'])}
        doc['stages']['9']=lane_settings(doc,{'lane_width_m':3})
        source=section_source(doc)
        spec={'name':'직선 코너','description':'코너','start':{'segment_index':20,'fraction':.4},'end':{'segment_index':70,'fraction':.7}}
        section=section_result(doc,[spec])['sections'][0]
        edges=lane_edges(source['points'],3)
        for key in ['start','end']:
            mark=section[key];i=mark['segment_index'];t=mark['fraction']
            for side in ['left','right']:
                for axis in ['e','n']:
                    self.assertAlmostEqual(mark[side][axis],edges[side][i][axis]*(1-t)+edges[side][i+1][axis]*t)
        self.assertAlmostEqual(section['start']['s_m'],2.04)

    async def test_insert_repairs_following_start_and_rejects_reversed_interval(self):
        def spec(name, start, end):
            return {'name':name,'description':name,'start':{'segment_index':int(start*100),'fraction':0.},'end':{'segment_index':int(end*100),'fraction':0.}}
        specs=[spec('first',0,.2),spec('insert',.2,.5),spec('following',.2,.8)]
        source=section_source(self.doc)
        saved=await self.post('save',{'filename':'lane.json','revision':1,'stage':10,'source_digest':source['source_digest'],'sections':specs})
        sections=saved['project']['stages']['10']['sections']
        self.assertEqual(sections[2]['start'],sections[1]['end'])
        self.assertAlmostEqual(sections[2]['end']['s_m'],8)
        self.assertEqual(final_map(saved['project'])['task_sections'],sections)
        specs[1]['end']['segment_index']=90
        await self.post('save',{'filename':'lane.json','revision':2,'stage':10,'source_digest':source['source_digest'],'sections':specs},400)
