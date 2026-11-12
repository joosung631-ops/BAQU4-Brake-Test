import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from aiohttp import web
from dashboard.camera_projection_config import projection_config
import test_gps_lane


class ProjectionConfigTests(unittest.TestCase):
    def test_relative_path_mounting_and_bad_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'path.jsonc').write_text('{"camera_intrinsics_file":"camera.yaml"}')
            config={'image_width':1280,'image_height':720,'camera_matrix':{'data':[800,0,640,0,800,360,0,0,1]},'distortion_model':'plumb_bob','distortion_coefficients':{'data':[0,0,0,0,0]}}
            vehicle={'camera':{'height_above_ground_m':1.14,'distance_from_rear_m':.861,'lateral_offset_m':0,'pitch_deg':0},'rear_axle_distance_from_rear_m':.225,'gps_antenna_offset_x_m':.559,'gps_antenna_offset_y_m':0}
            with patch.dict('os.environ',{'DASHBOARD_PATH_CONFIG':str(root/'path.jsonc')}),patch('dashboard.gps_path.vehicle_config',return_value=vehicle):
                (root/'camera.yaml').write_text(yaml.safe_dump(config))
                loaded=projection_config()
                self.assertEqual(loaded['path'],str(root/'camera.yaml'))
                self.assertEqual(loaded['camera']['pitch_deg'],0)
                self.assertEqual(loaded['calibration'],config)
                for key,value in [('image_width',0),('distortion_model','equidistant'),('camera_matrix',{'data':[0]*9}),('distortion_coefficients',{'data':[1,2]})]:
                    (root/'camera.yaml').write_text(yaml.safe_dump({**config,key:value}))
                    with self.assertRaises(web.HTTPBadRequest):projection_config()
                (root/'camera.yaml').write_text(yaml.safe_dump(config))
                vehicle['camera']['pitch_deg']=90
                with self.assertRaises(web.HTTPBadRequest):projection_config()


class ProjectionSaveTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_gps_lane.LaneApiTests.asyncSetUp
    asyncTearDown=test_gps_lane.LaneApiTests.asyncTearDown
    post=test_gps_lane.LaneApiTests.post
    source=test_gps_lane.LaneApiTests.source

    async def test_projection_controls_saved_and_reloaded(self):
        source=await self.source();self.config.write_text('{"lane_width_m":3.2}')
        preview=await self.post('lane-preview',{'filename':'lane.json','source_digest':source['source_digest']})
        body={'filename':'lane.json','revision':1,'stage':9,'source_digest':source['source_digest'],'road_digest':preview['settings']['road_digest'],'projection':{'enabled':True,'time_offset_s':.25,'show_lanes':False,'show_center':True,'show_sections':True}}
        saved=await self.post('save',body)
        self.assertEqual(saved['project']['stages']['9']['projection'],body['projection'])
        restored=await self.source()
        self.assertEqual(restored['saved']['projection'],body['projection'])
        before=self.file.read_bytes()
        await self.post('save',{**body,'revision':2,'projection':{'enabled':True,'time_offset_s':float('nan')}},400)
        self.assertEqual(before,self.file.read_bytes())
        cancel=await self.post('save',{**body,'revision':2,'enabled':False})
        self.assertFalse(cancel['project']['stages']['9']['enabled'])
        self.assertEqual(cancel['project']['stages']['9']['projection'],body['projection'])
