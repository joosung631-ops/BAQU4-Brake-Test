import math
import unittest
from aiohttp import web
from dashboard.gps_ordering import automatic_order,order_result

class OrderingTests(unittest.TestCase):
    def document(self):
        def p(x,y):return {'lat':math.degrees(y/(6378137*(1-6.6943799901413165e-3))),'lon':math.degrees(x/6378137),'source_ids':[f'{x}:{y}']}
        line=[{'e':0.,'n':0.,'seq':1},{'e':10.,'n':0.,'seq':2},{'e':10.,'n':10.,'seq':3}]
        return {'stages':{'2':{'raw':{'origin':[0,0]}},'3':{'tracks':[{'id':'a','name':'a','retained_points':[1,2,3],'curve_segments':[line]},{'id':'b','name':'b','retained_points':[1,2,3],'curve_segments':[list(reversed(line))]}]},'6':{'points':[p(8,1),p(2,.5),p(5,4),p(10,7)]}}}
    def test_projection_order_threshold_and_reference_direction(self):
        d=self.document();r=automatic_order(d,'a',1.1)
        self.assertEqual(r['auto_order'],[1,0,3]);self.assertFalse(r['matches'][2]['matched'])
        self.assertAlmostEqual(r['matches'][1]['distance_m'],.5,places=6)
        self.assertAlmostEqual(r['matches'][0]['path_m'],8,places=6)
        self.assertEqual(automatic_order(d,'b',1.1)['auto_order'],[3,0,1])
        for value in (0,-1,True,float('nan')):
            with self.assertRaises(web.HTTPBadRequest):automatic_order(d,'a',value)
    def test_manual_order_includes_unmatched_and_preserves_positions(self):
        d=self.document();r=order_result(d,'a',1.1,[2,1,0,3]);self.assertEqual([p['index'] for p in r['ordered_points']],[1,2,3,4])
        self.assertEqual(r['ordered_points'][0]['lat'],d['stages']['6']['points'][2]['lat']);self.assertEqual(r['unmatched_indices'],[])
        for order in ([0,0],[4],[True]):
            with self.assertRaises(web.HTTPBadRequest):order_result(d,'a',1,order)
    def test_no_projection_across_recording_gap(self):
        d=self.document();d['stages']['3']['tracks'][0]['curve_segments']=[[{'e':0,'n':0,'seq':1}],[{'e':10,'n':0,'seq':2}]]
        r=automatic_order(d,'a',1.1);self.assertEqual(r['auto_order'],[])
