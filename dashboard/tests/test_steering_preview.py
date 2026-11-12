import math
import time
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from dashboard.steering_preview import PredictionStore
from dashboard.brake import add_routes
from dashboard.traffic import BrowserTraffic


def sample():
    return dict(session='session0001',seq=1,angle_deg=5.,speed_mps=5.,brake=False,publish_cmd=False,
                sensors_fresh=True,wheelbase_m=1.328,width_m=1.28,lidar_x_m=.559,lidar_y_m=0.,yaw_deg=0.,cloud_stamp_s=1234.)


class StoreTests(unittest.TestCase):
    def test_fresh_copy_stale_sequence_and_expiry(self):
        store=PredictionStore();store.put(sample())
        self.assertEqual(store.snapshot(),sample())
        with self.assertRaises(ValueError):store.put(sample())
        copied=store.snapshot();copied['angle_deg']=10
        self.assertEqual(store.snapshot()['angle_deg'],5)
        with patch('dashboard.steering_preview.time.monotonic',return_value=time.monotonic()+1):self.assertIsNone(store.snapshot())

    def test_bad_units_types_and_nonfinite_do_not_replace_previous_value(self):
        store=PredictionStore();store.put(sample())
        for key,value in [('angle_deg',math.nan),('angle_deg',100),('width_m',True),('wheelbase_m',0),('seq',False),('publish_cmd',1),('speed_mps',math.inf)]:
            with self.assertRaises(ValueError):store.put(dict(sample(),seq=2,**{key:value}) if key!='seq' else dict(sample(),seq=value))
            self.assertEqual(store.snapshot()['seq'],1)

    def test_drive_status_validation_and_cloud_independent_speed(self):
        drive=dict(reason='sensor_or_path_lost',command_kph=0.,goal_kph=32.,max_speed_kph=35.,reached_max_speed=True,accelerating=False)
        value=dict(sample(),sensors_fresh=False,speed_mps=8.,brake=True,drive=drive)
        store=PredictionStore();store.put(value)
        self.assertEqual(store.snapshot()['drive'],drive)
        self.assertEqual(store.snapshot()['speed_mps'],8.)
        for key,v in [('command_kph',math.nan),('goal_kph',-1),('max_speed_kph',True),('accelerating',1),('reached_max_speed',None),('reason','<script>')]:
            with self.assertRaises(ValueError):store.put(dict(value,seq=2,drive=dict(drive,**{key:v})))
            self.assertEqual(store.snapshot()['seq'],1)

    def test_stop_recognition_and_braking_distances_are_nullable_and_bounded(self):
        drive=dict(reason='stop_row_braking',command_kph=0.,goal_kph=15.,max_speed_kph=15.,
                   reached_max_speed=True,accelerating=False,stop_state='confirmed',
                   stop_distance_m=10.4,brake_distance_m=10.5)
        store=PredictionStore();value=dict(sample(),brake=True,drive=drive)
        store.put(value);self.assertEqual(store.snapshot()['drive'],drive)
        for key,v in [('stop_state','<script>'),('stop_state',[]),('stop_distance_m',True),
                      ('stop_distance_m',math.nan),('stop_distance_m',-1),('brake_distance_m',math.inf),
                      ('brake_distance_m',1001)]:
            with self.assertRaises(ValueError):store.put(dict(value,seq=2,drive=dict(drive,**{key:v})))
            self.assertEqual(store.snapshot()['seq'],1)
        store.put(dict(value,seq=2,drive=dict(drive,stop_state='unavailable',stop_distance_m=None,brake_distance_m=None)))
        self.assertIsNone(store.snapshot()['drive']['stop_distance_m'])


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_display_upload_only_accepts_bounded_valid_data_and_has_no_control_action(self):
        app=web.Application();add_routes(app,BrowserTraffic())
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/brake/prediction',json=sample());self.assertEqual(response.status,200)
            response=await client.post('/api/brake/prediction',json=sample());self.assertEqual(response.status,400)
            response=await client.post('/api/brake/prediction',json={'actuate':True});self.assertEqual(response.status,400)
            response=await client.post('/api/brake/prediction',data='x'*3000,headers={'Content-Type':'application/json'});self.assertEqual(response.status,400)


if __name__=='__main__':unittest.main()
