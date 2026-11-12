import copy
import math
import unittest
from aiohttp import web
from dashboard.gps_linear import linear_source
from dashboard.gps_lane import lane_source, lane_settings
from dashboard.gps_review import digest
from dashboard.gps_export import final_map
from test_gps_path import document


def linear_document(xy):
    doc=document(xy)
    doc['stages']['8']={'draft':True,'valid':False,'source_digest':digest(doc['stages']['7'])}
    return doc


class LinearTests(unittest.TestCase):
    def test_exact_polyline_corners_spacing_stations_and_no_spline_fields(self):
        doc=linear_document([[0,0],[2.05,0],[2.05,2.03]])
        doc['stages']['8']['points']=[{'e':-99,'n':100,'heading_rad':-.7}]
        source=linear_source(doc);ps=source['points']
        self.assertEqual(source['reference_point'],'gps_antenna')
        self.assertEqual(source['interpolation'],'piecewise_linear')
        self.assertTrue(all(abs(p['n'])<1e-7 or abs(p['e']-2.05)<1e-7 for p in ps))
        corner=min(ps,key=lambda p:math.hypot(p['e']-2.05,p['n']))
        self.assertAlmostEqual(corner['e'],2.05,places=7);self.assertAlmostEqual(corner['n'],0,places=7)
        self.assertAlmostEqual(corner['heading_rad'],math.pi/2,places=6)
        self.assertAlmostEqual(ps[-1]['s_m'],4.08,places=7)
        self.assertTrue(all(0<b['s_m']-a['s_m']<=.10000001 for a,b in zip(ps,ps[1:])))
        self.assertTrue(all(math.hypot(b['e']-a['e'],b['n']-a['n'])<=.10000001 for a,b in zip(ps,ps[1:])))
        self.assertTrue(all('curvature_per_m' not in p and 'steering_deg' not in p for p in ps))
        previous=copy.deepcopy(source)
        doc['stages']['8']['points'][0]['e']=999
        self.assertEqual(linear_source(doc),previous)
        self.assertEqual(lane_source(doc),previous)

    def test_manual_edits_drive_lane_and_export_without_curve_validation(self):
        doc=linear_document([[0,0],[2,1],[5,0]])
        doc['stages']['8']['waypoints']=[{'id':'source-1'},{'id':'source-3'}]
        source=linear_source(doc)
        self.assertTrue(all(abs(p['n'])<1e-7 for p in source['points']))
        old_digest=source['source_digest']
        doc['stages']['9']=lane_settings(doc,{'lane_width_m':3})
        final=final_map(doc)
        self.assertEqual(final['points'],source['points'])
        self.assertEqual(final['reference_point'],'gps_antenna')
        self.assertEqual(final['spacing_policy'],'maximum_spacing_with_exact_waypoints')
        doc['stages']['8']['waypoints']=[{'id':'source-1'},{'id':'source-2'},{'id':'source-3'}]
        self.assertNotEqual(linear_source(doc)['source_digest'],old_digest)
        with self.assertRaises(web.HTTPConflict):final_map(doc)

    def test_old_curve_lane_results_and_invalid_paths_are_rejected(self):
        doc=linear_document([[0,0],[2,0]])
        doc['stages']['9']={'enabled':False,'source_digest':digest(doc['stages']['8'])}
        with self.assertRaises(web.HTTPConflict):final_map(doc)
        for waypoints in [[],[{'id':'source-1'}]]:
            doc['stages']['8']['waypoints']=waypoints
            with self.assertRaises(web.HTTPConflict):linear_source(doc)
        doc=linear_document([[0,0],[0,0]])
        with self.assertRaises(web.HTTPConflict):linear_source(doc)
        doc=linear_document([[0,0],[2,0]])
        doc['stages']['7']['matches'][1]['segment_index']=1
        doc['stages']['8']['source_digest']=digest(doc['stages']['7'])
        with self.assertRaises(web.HTTPConflict):linear_source(doc)
        doc=linear_document([[0,0],[2,0]])
        doc['stages']['8']['source_digest']='stale'
        with self.assertRaises(web.HTTPConflict):linear_source(doc)

    def test_exact_spacing_multiples_do_not_create_near_duplicate_corner_samples(self):
        ps=linear_source(linear_document([[0,0],[10,0],[10,10]]))['points']
        self.assertEqual(len(ps),201)
        self.assertTrue(all(.09999999<b['s_m']-a['s_m']<.10000001 for a,b in zip(ps,ps[1:])))
