import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from dashboard.gps_review import digest
from dashboard.map_compare import comparison_points, add_routes
from test_gps_path import document


class MapCompareTests(unittest.TestCase):
    def test_project_uses_gps_vertices_and_manual_edits_instead_of_rear_axle_spline(self):
        doc = document([[0, 0], [10, 0], [10, 10]])
        expected = copy.deepcopy(doc['stages']['7']['ordered_points'])
        doc['stages']['8'] = {'source_digest': digest(doc['stages']['7']),
            'points': [{'lat': 1, 'lon': 1}],
            'waypoints': [{'id': 'source-1'}, {'id': 'manual-compare', 'lat': 37.0001, 'lon': 127.0002, 'segment_index': 0}, {'id': 'source-3'}]}
        result = comparison_points(doc)
        self.assertEqual(result['point_count'], 3)
        self.assertEqual(result['points'][0]['lat'], expected[0]['lat'])
        self.assertEqual(result['points'][1]['lat'], 37.0001)
        self.assertEqual(result['points'][2]['lon'], expected[2]['lon'])
        self.assertEqual(result['interpolation'], 'piecewise_linear')
        doc['stages']['8']['source_digest'] = 'stale'
        result = comparison_points(doc)
        self.assertEqual(result['points'][1]['lat'], expected[1]['lat'])

    def test_breaks_are_preserved_between_project_segments(self):
        doc = document([[0, 0], [10, 0], [10, 10]])
        doc['stages']['7']['matches'][2]['segment_index'] = 1
        result = comparison_points(doc)
        self.assertFalse(result['points'][1]['break_before'])
        self.assertTrue(result['points'][2]['break_before'])

    def test_export_coordinates_are_not_resmoothed_and_bad_data_is_rejected(self):
        points = [{'lat': 37.1, 'lon': 127.1}, {'lat': 37.101, 'lon': 127.102, 'break_before': True}]
        doc = {'format': 'gps-final-map', 'points': points}
        result = comparison_points(doc)
        self.assertEqual(result['end']['lat'], points[-1]['lat'])
        self.assertTrue(result['end']['break_before'])
        for invalid in ({'points': []}, {'points': [{'lat': True, 'lon': 127}]},
                        {'format': 'gps-map-project', 'stages': {}},
                        {'points': [{'lat': float('nan'), 'lon': 127}]}):
            with self.assertRaises(ValueError):
                comparison_points(invalid)


class MapCompareWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_load_and_reject_unsafe_paths_without_writing(self):
        with tempfile.TemporaryDirectory() as root:
            maps = Path(root) / 'maps'; maps.mkdir()
            source = maps / '한글 MAP.json'
            body = json.dumps({'format': 'gps-final-map', 'points': [{'lat': 37, 'lon': 127}]})
            source.write_text(body)
            (maps / 'bad.json').write_text('{}')
            (maps / 'escape.json').symlink_to(source)
            (maps / 'array.json').write_text('[]')
            with patch.dict(os.environ, {'DASHBOARD_GPS_REVIEW_DIR': root}):
                app = web.Application(); add_routes(app)
                async with TestClient(TestServer(app)) as client:
                    names = await (await client.get('/api/map-compare/maps')).json()
                    self.assertEqual(names['maps'], ['array.json', 'bad.json', '한글 MAP.json'])
                    response = await client.get('/api/map-compare/maps/한글 MAP.json')
                    self.assertEqual(response.status, 200)
                    self.assertEqual((await response.json())['point_count'], 1)
                    for name in ('escape.json', 'missing.json', '..%2Fprivate.json'):
                        self.assertEqual((await client.get('/api/map-compare/maps/' + name)).status, 404)
                    for name in ('bad.json', 'array.json'):
                        self.assertEqual((await client.get('/api/map-compare/maps/' + name)).status, 400)
                    self.assertEqual((await client.post('/api/map-compare/maps/한글 MAP.json')).status, 405)
                    self.assertEqual(source.read_text(), body)
