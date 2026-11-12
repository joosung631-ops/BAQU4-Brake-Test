import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from dashboard.map_position import map_points,add_routes
from dashboard.gps_live import GPSLive
from dashboard.traffic import BrowserTraffic


P=[{'lat':37.3,'lon':126.8},{'lat':37.301,'lon':126.801}]


class MapPositionTests(unittest.TestCase):
    def test_final_and_project_saved_path_keep_order_and_endpoints(self):
        for document in ({'format':'gps-final-map','points':P},
                         {'format':'gps-map-project','stages':{'8':{'points':P}}}):
            result=map_points(document)
            self.assertEqual(result['point_count'],2);self.assertTrue(result['ordered'])
            self.assertEqual(result['start']['lat'],P[0]['lat']);self.assertEqual(result['end']['lat'],P[-1]['lat'])

    def test_early_project_tracks_preserve_breaks_and_note_file_order(self):
        result=map_points({'format':'gps-map-project','stages':{'3':{'tracks':[{'points':P},{'points':P}]}}})
        self.assertFalse(result['ordered']);self.assertTrue(result['points'][2]['break_before'])
        self.assertFalse(result['points'][1]['break_before'])
        retained=map_points({'format':'gps-map-project','stages':{'3':{'tracks':[{'retained_points':P}]}}})
        self.assertEqual(retained['point_count'],2)

    def test_bad_coordinate_or_empty_file_is_rejected(self):
        for document in ({'points':[]},{'points':[{'lat':float('nan'),'lon':127}]},
                         {'points':[{'lat':True,'lon':127}]},{'points':[{'lat':91,'lon':127}]}):
            with self.assertRaises(ValueError):map_points(document)

    def test_current_stale_clear_and_no_new_point(self):
        gps=GPSLive(None);self.assertIsNone(gps.current(now=0)['point'])
        p=dict(seq=1,t=100.,lat=37.3,lon=126.8,status=2,quality=4)
        gps.update({'session':'sensor','points':[p]},now=10)
        self.assertTrue(gps.current(now=11)['active']);self.assertFalse(gps.current(now=13)['active'])
        gps.clear();self.assertEqual(gps.current(now=11)['point']['lat'],37.3)
        gps.update({'session':'sensor','points':[p]},now=20)
        self.assertFalse(gps.current(now=20)['active'])


class MapPositionWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_read_only_load_and_current_fix(self):
        with tempfile.TemporaryDirectory() as directory:
            maps=Path(directory)/'maps';maps.mkdir();path=maps/'한글 MAP.json'
            body=json.dumps({'points':P});path.write_text(body)
            (maps/'bad.json').write_text('{}');(maps/'escape.json').symlink_to(path)
            with patch.dict(os.environ,{'DASHBOARD_GPS_REVIEW_DIR':directory}):
                app=web.Application();add_routes(app);gps=GPSLive(None);gps.add_routes(app,BrowserTraffic())
                async with TestClient(TestServer(app)) as client:
                    self.assertEqual((await (await client.get('/api/map-position/maps')).json())['maps'],['bad.json','한글 MAP.json'])
                    response=await client.get('/api/map-position/maps/한글 MAP.json')
                    self.assertEqual(response.status,200);self.assertEqual((await response.json())['end']['index'],2)
                    self.assertEqual((await client.get('/api/map-position/maps/bad.json')).status,400)
                    for name in ('escape.json','missing.json','..%2Fprivate.json'):
                        self.assertEqual((await client.get('/api/map-position/maps/'+name)).status,404)
                    self.assertEqual(path.read_text(),body)
                    response=await client.get('/api/gps/current');self.assertIsNone((await response.json())['point'])
                    await client.post('/api/ros/gps',json={'session':'sensor','points':[dict(seq=1,t=100.,lat=37.3,lon=126.8,status=2,quality=4)]})
                    current=await (await client.get('/api/gps/current')).json()
                    self.assertTrue(current['active']);self.assertEqual(current['point']['lat'],37.3)


if __name__=='__main__':unittest.main()
