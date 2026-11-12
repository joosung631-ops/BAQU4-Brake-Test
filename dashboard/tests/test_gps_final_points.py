"""Final insertions survive persistence and export without resampling base samples."""
import json
import unittest
from pathlib import Path
from dashboard.gps_export import final_map
from dashboard.gps_final_points import final_point_source
from dashboard.gps_lane import lane_source, lane_settings
from dashboard.gps_sections import section_result
import test_gps_lane


class FinalPointApiTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = test_gps_lane.LaneApiTests.asyncTearDown
    post = test_gps_lane.LaneApiTests.post

    async def asyncSetUp(self):
        await test_gps_lane.LaneApiTests.asyncSetUp(self)
        self.doc['stages']['9'] = lane_settings(self.doc, {'lane_width_m':3.2})
        self.doc['stages']['10'] = section_result(self.doc, [{'name':'task','description':'task',
            'start':{'segment_index':20,'fraction':.5},'end':{'segment_index':80,'fraction':.5}}])
        self.file.write_text(json.dumps(self.doc))
        self.source = final_point_source(self.doc)
        self.base = lane_source(self.doc)['points']

    def item(self, name, index, point=0):
        p = self.base[point]
        return {'id':'final-'+name,'index':index,'lat':p['lat']+.000001,'lon':p['lon']}

    async def save(self, additions, revision=1, status=200):
        return await self.post('save', {'filename':'lane.json','revision':revision,'stage':10.5,
            'source_digest':self.source['source_digest'],'additions':additions}, status)

    async def test_insert_first_middle_last_reorder_delete_reload_and_export(self):
        additions = [self.item('a',1),self.item('b',3,30),self.item('c',len(self.base)+3,100)]
        saved = await self.save(additions)
        final = final_map(saved['project'])
        self.assertEqual(len(final['points']),len(self.base)+3)
        self.assertEqual([p['index'] for p in final['points']],list(range(1,len(self.base)+4)))
        for item in additions:
            p = final['points'][item['index']-1]
            self.assertEqual((p['lat'],p['lon']),(item['lat'],item['lon']))
        remaining=[p for p in final['points'] if p['index'] not in {v['index'] for v in additions}]
        self.assertEqual([(p['lat'],p['lon']) for p in remaining],[(p['lat'],p['lon']) for p in self.base])
        self.assertTrue(all(b['s_m']>=a['s_m'] for a,b in zip(final['points'],final['points'][1:])))
        self.assertEqual(len(final['lanes']['boundaries']['left']),len(final['points']))
        self.assertEqual(final['task_sections'][0]['start']['center'],self.doc['stages']['10']['sections'][0]['start']['center'])
        response=await self.client.get('/api/gps/projects/lane-source?filename=lane.json&final=1')
        self.assertEqual((await response.json())['points'],final['points'])
        restored=await (await self.client.get('/api/gps/projects/final-waypoint-source?filename=lane.json')).json()
        self.assertEqual(restored['saved']['additions'],additions)
        moved=[{**additions[1],'index':1},{**additions[0],'index':2}]
        saved=await self.save(moved,2)
        self.assertEqual(final_map(saved['project'])['points'][0]['lat'],additions[1]['lat'])
        saved=await self.save([],3)
        self.assertEqual(final_map(saved['project'])['points'],self.base)
        saved=await self.save(moved,4)
        exported=await self.post('export',{'filename':'lane.json','revision':5,'new_filename':'final.json'})
        self.assertEqual(json.loads(Path(exported['export']['path']).read_text())['points'],final_map(saved['project'])['points'])

    async def test_invalid_input_and_stale_revision_leave_file_unchanged(self):
        good=self.item('a',1);before=self.file.read_bytes()
        for additions in [[{**good,'index':0}],[{**good,'index':1.5}],[{**good,'index':len(self.base)+2}],
                          [{**good,'lat':91}],[{**good,'lon':float('nan')}],[good,good],
                          [good,{**good,'id':'final-b'}],[{**good,'index':True}]]:
            await self.save(additions,status=400)
            self.assertEqual(self.file.read_bytes(),before)
        await self.save([good],revision=0,status=409)
        await self.post('save',{'filename':'lane.json','revision':1,'stage':10.5,'source_digest':'stale','additions':[good]},409)
        self.assertEqual(self.file.read_bytes(),before)

    async def test_invalidation_and_fractional_stage_resume_rewind(self):
        saved=await self.save([self.item('a',2)])
        saved=await self.post('save',{'filename':'lane.json','revision':2,'stage':11,'validated_bags':[]})
        self.assertIn('11',saved['project']['stages'])
        saved=await self.save([self.item('a',3)],3)
        self.assertNotIn('11',saved['project']['stages'])
        resumed=await self.post('resume',{'filename':'lane.json','revision':4})
        self.assertTrue(resumed['filename'].startswith('11단계_'))
        rewound=await self.post('rewind',{'filename':resumed['filename'],'revision':resumed['project']['revision'],'stage':10})
        self.assertNotIn('10.5',rewound['project']['stages'])
        self.assertIn('10',rewound['project']['stages'])
