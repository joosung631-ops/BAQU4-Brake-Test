import json
from pathlib import Path
import tempfile
import unittest

from run_report import analyse,render


def fixture():
    # Northbound driving: x axis must use northward projection, not world east or path length.
    odometry=[dict(time=i*.1,stamp_ns=i+1,position_m=[100.+(2. if i==8 else 0.),200.+i],
                   frame='map',speed_mps=0. if i>=8 else 10.) for i in range(10)]
    return dict(schema=1,started=0.,brake_time=.5,stopped_since=.8,confirmed_at=.9,stop_confirmed=True,
        completed_at='2026-10-30T00:37:35+09:00',output_name='261030_003735',max_speed_kph=36.,
        config=dict(sensor_timeout_s=.35,lidar_yaw_offset_deg=0.),speeds={},reason='stop_row_braking',
        odometry=odometry,
        commands=[dict(time=.05,raw=[0.,.4,0.],target_kph=35.,published=True,reason='accelerate'),
                  dict(time=.5,raw=[0.,.4,1.],target_kph=35.,published=True,reason='stop_row_braking'),
                  dict(time=.85,raw=[0.,0.,1.],target_kph=0.,published=True,reason='stop_row_braking')],
        scans=[dict(time=.25,frame=1,cones_lidar_m=[[-10.,1.,-1.]],row_distance_m=12.,row_state='confirmed'),
               dict(time=.35,frame=2,cones_lidar_m=[],row_distance_m=None,row_state='none')])


class ReportTest(unittest.TestCase):
    def test_projected_displacement_interpolates_command_and_cone_positions(self):
        data=analyse(fixture())
        self.assertEqual(data['direction'],[0.,1.])
        self.assertAlmostEqual(data['commands'][0]['x'],.5)
        self.assertAlmostEqual(data['cones'][0]['x'],2.5)
        self.assertEqual(data['cones'][0]['distance_m'],10.)
        self.assertEqual(len(data['rows']),1)
        self.assertEqual(data['speed'][8]['x'],8.)

    def test_missing_position_and_gnss_gap_are_not_filled_by_commanded_speed(self):
        job=fixture();job['odometry'][2]['position_m']=None
        self.assertIsNone(analyse(job)['cones'][0]['x'])
        job=fixture();job['odometry']=[job['odometry'][0],job['odometry'][-1]]
        self.assertIsNone(analyse(job)['commands'][1]['x'])
        job=fixture()
        for s in job['odometry']:s['position_m']=None
        data=analyse(job);self.assertTrue(data['warnings']);self.assertTrue(all(s['x'] is None for s in data['commands']))

    def test_png_and_data_files_and_output_collision_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job=root/'job.json';job.write_text(json.dumps(fixture()))
            first=render(job,root/'ouput');second=render(job,root/'ouput')
            self.assertEqual(first.parent.name,'261030_003735');self.assertEqual(second.parent.name,'261030_003735_01')
            self.assertEqual(first.read_bytes()[:8],b'\x89PNG\r\n\x1a\n');self.assertGreater(first.stat().st_size,30000)
            self.assertTrue((first.parent/'samples.csv').exists());self.assertTrue((first.parent/'cones.csv').exists())
            summary=json.loads((first.parent/'summary.json').read_text())
            self.assertEqual(summary['max_speed_kph'],36.);self.assertTrue(summary['stop_confirmed'])


if __name__=='__main__':unittest.main()
