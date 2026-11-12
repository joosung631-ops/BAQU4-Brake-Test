import json
from pathlib import Path
import tempfile
import unittest

from telemetry import RunTelemetry,write_job


def command(brake=False,motor=.2):
    return dict(raw=[0.,motor,float(brake)],brake=brake,reason='stop_row_braking' if brake else 'accelerate',
                target_kph=motor*35.)


class TelemetryTest(unittest.TestCase):
    def test_max_speed_and_full_stop_require_observation_not_just_brake_or_zero_motor(self):
        r=RunTelemetry(.35)
        r.odom(0.,1,0.,[0.,0.],'map');r.start(.01)
        r.command(.02,command(),True)
        r.odom(.1,2,10.,[1.,0.],'map')
        r.command(.2,command(True,0.),True)
        self.assertFalse(r.stopped(.2))
        for i in range(6):
            now=.3+i*.1;r.odom(now,3+i,0.,[2.,0.],'map')
        self.assertTrue(r.stopped(.81))
        report=r.snapshot(.81,dict(sensor_timeout_s=.35),{},'stop_row_braking')
        self.assertEqual(report['max_speed_kph'],36.)
        self.assertEqual(report['output_name'][6],'_');self.assertEqual(len(report['output_name']),13)
        self.assertEqual(len(report['commands']),2)
        r.odom(1.,10,99.,[50.,0.],'map')
        self.assertEqual(len(r.odometry),8)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json';write_job(path,report)
            self.assertTrue(json.loads(path.read_text())['stop_confirmed']);self.assertFalse(path.with_suffix('.tmp').exists())

    def test_invalid_speed_sensor_gap_and_moving_sample_restart_stop_confirmation(self):
        for cause in ('invalid','gap','moving'):
            r=RunTelemetry(.35);r.start(0);r.command(0,command(True,0.),True)
            r.odom(.1,1,0.,[0,0],'map');r.odom(.2,2,0.,[0,0],'map')
            if cause=='invalid':r.odom(.3,3,None,[0,0],'map')
            if cause=='moving':r.odom(.3,3,.2,[0,0],'map')
            r.odom(.7,4,0.,[0,0],'map');self.assertFalse(r.stopped(.8))
            for i in range(1,7):r.odom(.7+i*.1,4+i,0.,[0,0],'map')
            self.assertTrue(r.stopped(1.31));self.assertFalse(r.stopped(2.))

    def test_ramp_must_reach_zero_and_scans_store_measured_cones_without_zero_filling(self):
        r=RunTelemetry(.35);r.start(0);r.command(0,command(True,.2),False)
        for i in range(7):r.odom(i*.1,1+i,0.,[0,0],'map')
        self.assertFalse(r.stopped(.61))
        r.command(.61,command(True,0.),False);self.assertTrue(r.stopped(.61))
        r.scan(dict(time=.1,frame=1,cones_lidar_m=[[-10.,1.,-1.]],stop_state='candidate',stop_distance_m=10.))
        r.scan(dict(time=.2,frame=2,stop_state='none',stop_distance_m=0.))
        self.assertEqual(r.scans[0]['row_distance_m'],10.)
        self.assertIsNone(r.scans[1]['row_distance_m']);self.assertEqual(r.scans[1]['cones_lidar_m'],[])


if __name__=='__main__':unittest.main()
