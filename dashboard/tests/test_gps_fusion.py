import math
import unittest
from aiohttp import web
from dashboard.gps_fusion import automatic_groups,fused_points
from dashboard.gps_review import project

class FusionTests(unittest.TestCase):
    def setUp(self):
        self.source=[{'id':str(i),'track_id':str(i%2),'lat':0.,'lon':math.degrees(x/6378137)} for i,x in enumerate([0.,.75,1.5,20.])]
        self.groups=[[p['id']] for p in self.source]
    def test_selected_only_and_no_transitive_chain(self):
        result=automatic_groups(self.source,self.groups,[0,1,2],1.,[0,0])
        self.assertEqual(result,[['0','1'],['2'],['3']])
        result=automatic_groups(self.source,self.groups,[0,1],1.,[0,0])
        self.assertEqual(result,[['0','1'],['2'],['3']])
        pts=project(self.source,[0,0]);distance=math.hypot(pts[0]['e']-pts[1]['e'],pts[0]['n']-pts[1]['n'])
        self.assertEqual(automatic_groups(self.source,self.groups,[0,1],distance,[0,0]),self.groups)
    def test_lineage_weighting_and_partition_validation(self):
        merged=fused_points(self.source,[['0','1','2'],['3']])
        self.assertEqual(merged[0]['source_track_ids'],['0','1']);self.assertEqual(merged[0]['count'],3)
        self.assertAlmostEqual(merged[0]['lon'],self.source[1]['lon'])
        for bad in ([['0','1'],['1','3']],[['0'],['1'],['3']]):
            with self.assertRaises(web.HTTPBadRequest):fused_points(self.source,bad)
        for radius in (0,-1,float('nan'),True,1e-100):
            with self.assertRaises(web.HTTPBadRequest):automatic_groups(self.source,self.groups,[0,1],radius,[0,0])

    def test_curves_follow_recording_order_and_keep_gaps(self):
        from dashboard.gps_fusion import fusion_curves
        source=[{'id':str(i),'track_id':track,'color_index':color,'segment':segment,'lat':37+i*.00001,'lon':127} for i,track,color,segment in [(0,'a',0,0),(1,'a',0,0),(2,'a',0,1),(3,'b',1,0),(4,'b',1,0)]]
        result=fusion_curves(source,[['0','3'],['1','4'],['2']],[37,127])
        self.assertEqual([t['id'] for t in result],['a','b'])
        self.assertEqual(len(result[0]['curve_segments']),2)
        self.assertEqual(len(result[1]['curve_segments']),1)
        self.assertEqual(result[0]['curve_segments'][0],result[1]['curve_segments'][0])
        self.assertEqual(len(result[0]['curve_segments'][1]),1)
