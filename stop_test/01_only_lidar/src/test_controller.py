import math
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(os.environ.get('TEST_REPO','/repo'))
STOP=ROOT/'stop_test' if (ROOT/'stop_test/01_only_lidar').exists() else ROOT
sys.path.insert(0,str(STOP/'01_only_lidar/vendor'))
from controller import Core,Controller
try:import tomllib
except ImportError:import tomli as tomllib

# Stable fixtures: operator edits to live speed/braking settings must not change tests.
CFG=dict(tomllib.loads((STOP/'01_only_lidar/config.toml').read_text()),
         publish_cmd=False,front_from_lidar_m=1.438,stop_margin_m=2.,reaction_s=.3,
         brake_decel_mps2=3.,max_accel_kphps=10.,brake_motor_ramp_enabled=False,
         brake_motor_ramp_35_to_zero_s=1.,brake_steering_return_enabled=False,
         brake_steering_full_left_to_zero_s=1.,path_loss_stop_frames=20)
SPEEDS=dict(max_speed=35.,high_speed=32.,low_speed=20.,use_high_speed=False,
            blind_start_kph=5.,blind_start_timeout_s=5.,line_confirm_frames=1)


class Tests(unittest.TestCase):
    def setUp(self):self.core=Core(os.environ['TEST_CORE']);self.c=self.make()
    def make(self,speeds=SPEEDS,cfg=CFG,phase='drive'):
        c=Controller(self.core,speeds,cfg)
        if phase!='hold':self.assertTrue(c.begin(0,blind=phase=='blind'))
        return c
    def obs(self,t,d=None,y=0):
        return dict(time=t,frame=t,path=[[2,y],[20,y]],ground='near_verified',
                    stop_state='confirmed' if d is not None else 'none',stop_distance_m=d)
    def test_existing_pp_and_trans_sign_and_scale(self):
        left=self.core.steering([[2,1],[20,1]],5)
        self.assertGreater(left,0)
        self.assertLess(self.core.raw(left,35/3.6,False,0,.47)[0],0)
        raw=self.core.raw(0,35/3.6,False,0,.47)
        self.assertAlmostEqual(raw[1],(35/3.6)*60/(math.pi*.47)/891.387,places=6)
        self.assertEqual(raw[2],0)
        self.assertEqual(self.core.raw(left,35/3.6,True,0,.47)[1:],[0,1])
    def test_dryrun_and_startup_wait(self):
        self.assertFalse(CFG['publish_cmd'])
        r=self.c.step(None,None,None,0,.02);self.assertEqual(r['raw'],[0,0,1])
        r=self.c.step(self.obs(.1),0,.1,.1,.02);self.assertFalse(r['brake'])
    def test_speed_milestone_uses_measured_speed_and_both_modes(self):
        for high,key in [(True,'high_speed'),(False,'low_speed')]:
            c=self.make(dict(SPEEDS,use_high_speed=high))
            for i in range(200):r=c.step(self.obs(i*.02),0,i*.02,i*.02,.02)
            self.assertAlmostEqual(r['target_kph'],35)
            self.assertFalse(r['reached_max_speed'])
            r=c.step(self.obs(4),35/3.6,4,4,.02)
            self.assertAlmostEqual(r['target_kph'],SPEEDS[key]);self.assertTrue(r['reached_max_speed'])
    def test_far_detection_does_not_brake_immediately_and_near_does_before_milestone(self):
        r=self.c.step(self.obs(0,40),0,0,0,.02);self.assertFalse(r['brake'])
        r=self.c.step(self.obs(.1,18),35/3.6,.1,.1,.02)
        self.assertTrue(r['brake']);self.assertEqual(r['raw'][1:],[0,1])
        r=self.c.step(self.obs(.2,40),0,.2,.2,.02);self.assertTrue(r['brake'])
    def test_lost_path_latches_brake_and_holds_steering(self):
        r=self.c.step(self.obs(0,y=1),3,0,0,.02);angle=r['raw'][0]
        r=self.c.step(None,3,.4,.4,.02)
        self.assertTrue(r['brake']);self.assertEqual(r['raw'][0],angle)
        r=self.c.step(self.obs(.5),3,.5,.5,.02);self.assertTrue(r['brake'])
    def test_unconfirmed_row_cannot_set_stop_track(self):
        o=self.obs(0,2);o['stop_state']='candidate'
        self.assertFalse(self.c.step(o,0,0,0,.02)['brake']);self.assertIsNone(self.c.distance)
    def test_confirmed_track_survives_row_loss_with_odometry(self):
        self.assertFalse(self.c.step(self.obs(0,30),10,0,0,.02)['brake'])
        for i in range(1,10):r=self.c.step(self.obs(i*.1),10,i*.1,i*.1,.1)
        self.assertTrue(r['brake']);self.assertLess(self.c.distance,30)
    def test_first_braking_reason_and_threshold_survive_path_loss_and_fault(self):
        first=self.c.step(self.obs(0,4),4,0,0,.02)
        self.assertEqual(first['reason'],'stop_row_braking')
        for fault in (None,'another_cmd_publisher'):
            r=self.c.step(None,4,.1,.1,.02,fault)
            self.assertEqual(r['reason'],'stop_row_braking')
            self.assertEqual(r['brake_distance_m'],first['brake_distance_m'])
            self.assertEqual(r['raw'][1:],[0,1])
    def test_protective_stop_remains_distinct_from_stop_row_braking(self):
        self.c.step(self.obs(0),4,0,0,.02)
        self.assertEqual(self.c.step(None,4,.1,.1,.02)['reason'],'sensor_or_path_lost')
        r=self.c.step(self.obs(.2,2),4,.2,.2,.02)
        self.assertEqual(r['reason'],'sensor_or_path_lost');self.assertEqual(r['raw'][1:],[0,1])
    def test_larger_margin_starts_braking_four_metres_earlier_at_15_kph(self):
        results=[]
        for margin in (2.,6.):
            c=self.make(cfg=dict(CFG,stop_margin_m=margin,brake_decel_mps2=5.))
            results.append(c.step(self.obs(0,9),15/3.6,0,0,.02))
        self.assertFalse(results[0]['brake']);self.assertTrue(results[1]['brake'])
        self.assertAlmostEqual(results[0]['brake_distance_m'],6.4241111111)
        self.assertAlmostEqual(results[1]['brake_distance_m']-results[0]['brake_distance_m'],4.)
    def test_stale_odom_ground_failure_and_conflicting_source(self):
        for obs,speed_time,fault in [(self.obs(.5),0,None),(dict(self.obs(.5),ground='unreliable'),.5,None),(self.obs(.5),.5,'another_cmd_publisher')]:
            c=self.make();c.step(self.obs(0),0,0,0,.02)
            self.assertTrue(c.step(obs,1,speed_time,.5,.02,fault)['brake'])

    def nopath(self,t):return dict(self.obs(t),path=None,ground='unchecked')

    def test_path_loss_counts_twenty_lidar_frames_and_holds_last_command(self):
        for test_mode in (True,False):
            c=self.make(dict(SPEEDS,test_mode=test_mode))
            before=c.step(self.obs(0,y=1),3.,0,0,.02)
            for i in range(1,21):
                now=i*.1;obs=self.nopath(now)
                r=c.step(obs,3.,now,now,.02)
                self.assertEqual(r['path_missing_frames'],i)
                self.assertEqual(r['path_loss_stop_frames'],20)
                self.assertEqual(r['raw'][0],before['raw'][0])
                if i==20:
                    self.assertEqual(r['raw'][1:],[0,1])
                    self.assertEqual(r['reason'],'sensor_or_path_lost')
                else:
                    self.assertEqual(r['raw'],before['raw'])
                    self.assertEqual(r['target_kph'],before['target_kph'])
                    self.assertEqual(r['reason'],'path_loss_grace')
                    # Five 50Hz timer calls for one 10Hz lidar frame still count once.
                    for j in range(1,5):
                        tick=now+j*.02
                        r=c.step(obs,3.,tick,tick,.02)
                        self.assertEqual(r['path_missing_frames'],i)
                        self.assertEqual(r['raw'],before['raw'])
            recovered=c.step(self.obs(2.1),3.,2.1,2.1,.02)
            self.assertTrue(recovered['brake'])
            self.assertEqual(recovered['reason'],'sensor_or_path_lost')

    def test_path_recovery_resets_consecutive_run_and_resumes_tracking(self):
        c=self.make();before=c.step(self.obs(0,y=1),3.,0,0,.02)
        for i in range(1,20):
            now=i*.1
            self.assertFalse(c.step(self.nopath(now),3.,now,now,.02)['brake'])
        recovered=c.step(self.obs(2.,y=-1),3.,2.,2.,.02)
        self.assertEqual(recovered['path_missing_frames'],0)
        self.assertEqual(recovered['reason'],'accelerate')
        self.assertGreater(recovered['target_kph'],before['target_kph'])
        self.assertNotEqual(recovered['raw'][0],before['raw'][0])
        for i in range(1,20):
            now=2.+i*.1
            r=c.step(self.nopath(now),3.,now,now,.02)
            self.assertEqual(r['path_missing_frames'],i);self.assertFalse(r['brake'])
        self.assertTrue(c.step(self.nopath(4.),3.,4.,4.,.02)['brake'])

    def test_sensor_ground_and_external_faults_stop_during_path_grace_immediately(self):
        cases=[(None,3.,.2,.2,None),
               (self.nopath(.1),3.,.5,.5,None),
               (self.nopath(.5),3.,.1,.5,None),
               (self.nopath(.2),None,.2,.2,None),
               (dict(self.nopath(.2),ground='unreliable'),3.,.2,.2,None),
               (dict(self.obs(.2),ground='unreliable'),3.,.2,.2,None),
               (self.nopath(.2),3.,.2,.2,'another_cmd_publisher'),
               (self.nopath(.2),3.,.2,.2,'bag_replay_detected')]
        for observation,speed,speed_time,now,fault in cases:
            c=self.make();c.step(self.obs(0),3.,0,0,.02)
            self.assertFalse(c.step(self.nopath(.1),3.,.1,.1,.02)['brake'])
            r=c.step(observation,speed,speed_time,now,.02,fault)
            self.assertEqual(r['raw'][1:],[0,1])
            self.assertEqual(r['reason'],fault or 'sensor_or_path_lost')
        c=self.make();c.step(self.obs(0),3.,0,0,.02)
        c.step(self.nopath(.1),3.,.1,.1,.02);c.stop('operator_stop')
        self.assertEqual(c.step(self.nopath(.2),3.,.2,.2,.02)['raw'][1:],[0,1])

    def test_remembered_stop_row_brakes_before_path_grace_expires(self):
        c=self.make();self.assertFalse(c.step(self.obs(0,8.),4.,0,0,.02)['brake'])
        self.assertFalse(c.step(self.nopath(.1),4.,.1,.1,.02)['brake'])
        r=c.step(self.nopath(.2),4.,.2,.2,.02)
        self.assertEqual(r['path_missing_frames'],2)
        self.assertEqual(r['reason'],'stop_row_braking');self.assertEqual(r['raw'][1:],[0,1])

    def test_real_start_without_initial_path_holds_creep_until_twentieth_scan(self):
        c=self.make(dict(SPEEDS,test_mode=False),phase='hold')
        initial=c.step(self.nopath(0),1.,0,0,.02)
        self.assertEqual(initial['target_kph'],5.);self.assertTrue(c.begin(.1))
        for i in range(1,20):
            now=i*.1;r=c.step(self.nopath(now),1.,now,now,.02)
            self.assertEqual(r['raw'],initial['raw']);self.assertEqual(r['path_missing_frames'],i)
        self.assertEqual(c.step(self.nopath(2.),1.,2.,2.,.02)['raw'][1:],[0,1])

    def test_path_loss_frame_setting_validation_and_default(self):
        for value in (0,-1,True,False,20.,'20',None):
            with self.assertRaises(ValueError,msg=value):self.make(cfg=dict(CFG,path_loss_stop_frames=value))
        old=dict(CFG);old.pop('path_loss_stop_frames')
        self.assertEqual(self.make(cfg=old).path_loss_stop_frames,20)
        c=self.make(cfg=dict(CFG,path_loss_stop_frames=1));c.step(self.obs(0),3.,0,0,.02)
        self.assertEqual(c.step(self.nopath(.1),3.,.1,.1,.02)['raw'][1:],[0,1])

    def test_hold_brakes_and_counts_distinct_consecutive_line_frames(self):
        c=self.make(dict(SPEEDS,line_confirm_frames=3),phase='hold')
        for i in range(3):
            self.assertFalse(c.lines_confirmed())
            r=c.step(self.obs(i*.1),0,i*.1,i*.1,.02)
            self.assertTrue(r['brake']);self.assertEqual(r['reason'],'operator_wait');self.assertEqual(r['raw'][1:],[0,1])
        self.assertTrue(c.lines_confirmed())
        c.step(self.nopath(.3),0,.3,.3,.02);self.assertEqual(c.lines,0)
        same=self.obs(.4);c.step(same,0,.4,.4,.02);c.step(same,0,.41,.41,.02);self.assertEqual(c.lines,1)
        c.step(None,0,.8,.8,.02);self.assertEqual(c.lines,0)
    def test_fault_while_holding_latches_and_refuses_start(self):
        c=self.make(phase='hold')
        self.assertEqual(c.step(self.obs(0),0,0,0,.02,'another_cmd_publisher')['reason'],'another_cmd_publisher')
        self.assertFalse(c.begin(0));self.assertEqual(c.phase,'hold')
    def test_real_start_creeps_at_configured_speed_and_counts_only_new_motion_samples(self):
        c=self.make(dict(SPEEDS,test_mode=False,startup_speed_kph=3.,line_confirm_frames=3),phase='hold')
        initial=c.step(None,None,None,0,.02)
        self.assertFalse(initial['brake']);self.assertEqual(initial['target_kph'],3.)
        first=c.step(None,0.,.1,.1,.02)
        self.assertEqual(first['reason'],'startup_wait_motion');self.assertFalse(first['brake'])
        self.assertEqual(first['target_kph'],3.);self.assertEqual(c.startup_motion_count,0)
        for i in range(1,5):
            r=c.step(None,0.,.1,.1+i*.02,.02)
            self.assertEqual(c.startup_motion_count,0);self.assertEqual(r['target_kph'],3.)
        c.step(None,1.,.2,.2,.02);self.assertEqual(c.startup_motion_count,1)
        c.step(None,1.,.2,.22,.02);self.assertEqual(c.startup_motion_count,1)
        c.step(None,.05,.25,.25,.02);self.assertEqual(c.startup_motion_count,0)
        for i,now in enumerate((.3,.35,.4),1):
            c.step(None,1.,now,now,.02);self.assertEqual(c.startup_motion_count,i)
        self.assertEqual(c.phase,'hold')
        self.assertTrue(c.begin(.4))
        r=c.step(self.obs(.42),1.,.42,.42,.02)
        self.assertEqual(c.lines,1);self.assertFalse(c.lines_confirmed())
        self.assertEqual(r['reason'],'accelerate');self.assertAlmostEqual(r['target_kph'],3.2)
    def test_real_creep_does_not_wait_for_sensor_readiness_or_latch_on_missing_data(self):
        c=self.make(dict(SPEEDS,test_mode=False),phase='hold')
        for now in (0.,.5,1.):
            r=c.step(None,None,None,now,.02)
            self.assertFalse(r['brake']);self.assertEqual(r['target_kph'],5.)
            self.assertIsNone(c.latched);self.assertEqual(c.startup_motion_count,0)
        c.step(None,1.,1.1,1.1,.02);self.assertEqual(c.startup_motion_count,1)
        r=c.step(None,1.,1.1,1.5,.02)
        self.assertFalse(r['brake']);self.assertEqual(c.startup_motion_count,0)
        self.assertTrue(c.begin(1.5))
        r=c.step(None,1.,1.6,1.6,.02)
        self.assertEqual(r['reason'],'sensor_or_path_lost');self.assertEqual(r['raw'][1:],[0,1])
    def test_real_start_retains_stop_row_and_external_fault_braking(self):
        for fault in ('another_cmd_publisher','bag_replay_detected','operator_stop'):
            c=self.make(dict(SPEEDS,test_mode=False),phase='hold')
            self.assertEqual(c.startup_speed_kph,5.)
            self.assertFalse(c.step(self.obs(0),0.,0,0,.02)['brake'])
            if fault=='operator_stop':c.stop(fault)
            r=c.step(self.obs(.4),0.,.4,.4,.02,
                     fault if fault in ('another_cmd_publisher','bag_replay_detected') else None)
            self.assertEqual(r['reason'],fault);self.assertEqual(r['raw'][1:],[0,1])
            self.assertFalse(c.begin(.4))
            self.assertEqual(c.step(self.obs(.5),1.,.5,.5,.02)['raw'][1:],[0,1])
        c=self.make(dict(SPEEDS,test_mode=False),phase='hold')
        r=c.step(self.obs(0,1.),0.,0,0,.02)
        self.assertEqual(r['reason'],'stop_row_braking');self.assertEqual(r['raw'][1:],[0,1])
    def test_real_start_settings_validation_and_old_config_defaults_to_test(self):
        self.assertTrue(self.make(phase='hold').test_mode)
        for value in (0,1,'false',None):
            with self.assertRaises(ValueError):self.make(dict(SPEEDS,test_mode=value),phase='hold')
        for value in (0.,-1.,11.,float('nan'),float('inf'),True,'5',None):
            with self.assertRaises(ValueError):self.make(dict(SPEEDS,startup_speed_kph=value),phase='hold')
    def test_drive_start_waits_for_confirmed_lines(self):
        c=self.make(dict(SPEEDS,line_confirm_frames=3))
        for i in range(2):
            r=c.step(self.obs(i*.1),0,i*.1,i*.1,.02);self.assertTrue(r['brake']);self.assertEqual(r['reason'],'waiting_for_sensors')
        self.assertFalse(c.step(self.obs(.2),0,.2,.2,.02)['brake'])
    def test_blind_start_creeps_straight_then_accelerates_once_lines_confirmed(self):
        cfg=dict(CFG,steering_zero_deg=1.)
        c=self.make(dict(SPEEDS,line_confirm_frames=3),cfg,phase='blind')
        for i in range(100):r=c.step(self.nopath(i*.02),1.,i*.02,i*.02,.02)
        self.assertFalse(r['brake']);self.assertEqual(r['reason'],'blind_start')
        self.assertAlmostEqual(r['target_kph'],5)
        self.assertEqual(r['raw'],self.core.raw(0,5/3.6,False,1.,cfg['wheel_diameter_m']))
        for i,t in enumerate((2.,2.02,2.04)):
            r=c.step(self.obs(t,y=1),1.,t,t,.02)
            self.assertEqual(c.phase,'blind' if i<2 else 'drive')
        self.assertEqual(r['reason'],'accelerate');self.assertAlmostEqual(r['target_kph'],5.2)
        self.assertNotEqual(r['raw'][0],self.core.raw(0,1,False,1.,cfg['wheel_diameter_m'])[0])
    def test_blind_start_timeout_latches_brake_with_distance(self):
        c=self.make(phase='blind')
        for i in range(260):r=c.step(self.nopath(i*.02),1.,i*.02,i*.02,.02)
        self.assertTrue(r['brake']);self.assertEqual(r['reason'],'blind_start_timeout');self.assertEqual(r['raw'][1:],[0,1])
        self.assertAlmostEqual(c.blind_distance,5,delta=.05)
        self.assertEqual(c.step(self.obs(5.3),1.,5.3,5.3,.02)['reason'],'blind_start_timeout')
    def test_blind_start_sensor_or_speed_loss_latches_brake(self):
        for obs,speed_time in ((None,.5),(self.nopath(.5),0)):
            c=self.make(phase='blind');c.step(self.nopath(0),1.,0,0,.02)
            r=c.step(obs,1.,speed_time,.5,.02)
            self.assertTrue(r['brake']);self.assertEqual(r['reason'],'blind_start_sensor_lost')
    def test_operator_settings_are_validated(self):
        for bad in (dict(blind_start_kph=35.),dict(blind_start_kph=-1.),dict(blind_start_timeout_s=0),
                    dict(blind_start_timeout_s=11),dict(line_confirm_frames=0),dict(line_confirm_frames=3.),
                    dict(line_confirm_frames=True)):
            with self.assertRaises(ValueError,msg=bad):Controller(self.core,dict(SPEEDS,**bad),CFG)
        Controller(self.core,dict(SPEEDS,blind_start_kph=0),CFG)

    def ramp_start(self,reference=1.,command=35.,enabled=True):
        c=self.make(speeds=dict(SPEEDS,max_speed=command),cfg=dict(CFG,brake_motor_ramp_enabled=enabled,
                             brake_motor_ramp_35_to_zero_s=reference))
        now=0.
        # Build the command through normal driving, with a slower measured speed.
        while c.target*3.6<command-1e-8:
            c.step(self.obs(now,y=1),4.,now,now,.02)
            now+=.02
        r=c.step(self.obs(now,1.,y=1),4.,now,now,.02)
        return c,now,r

    def test_ramp_brakes_immediately_and_converts_decreasing_command_with_held_steering(self):
        c,start,r=self.ramp_start()
        self.assertTrue(r['brake']);self.assertEqual(r['raw'][2],1)
        self.assertAlmostEqual(r['target_kph'],35.)
        held=r['raw'][0]
        for elapsed,expected in ((.02,34.3),(.25,26.25),(.5,17.5),(.9,3.5),(1.,0.),(1.5,0.)):
            now=start+elapsed
            r=c.step(self.obs(now,40.,y=-1),4.,now,now,.02)
            self.assertAlmostEqual(r['target_kph'],expected)
            self.assertEqual(r['raw'][0],held);self.assertEqual(r['raw'][2],1)
            self.assertAlmostEqual(r['raw'][1],expected/3.6*60/(math.pi*.47)/891.387,places=6)
        self.assertEqual(r['brake_motor_ramp']['state'],'completed')

    def test_reference_time_scales_with_initial_command_and_ignores_capped_dt(self):
        for reference,command,seconds in ((1.,17.5,.5),(.5,35.,.5),(2.,35.,2.)):
            c,start,r=self.ramp_start(reference,command)
            initial=r['target_kph']
            now=start+seconds/2
            r=c.step(self.obs(now),4.,now,now,.001)
            self.assertAlmostEqual(r['target_kph'],initial/2)
            now=start+seconds+.01
            self.assertEqual(c.step(self.obs(now),4.,now,now,.001)['raw'][1:],[0,1])

    def test_disabled_ramp_ignores_duration_and_old_config_keeps_immediate_zero(self):
        for duration in (0.,-1.,float('nan'),'unused'):
            c,_,r=self.ramp_start(duration,enabled=False)
            self.assertEqual(r['raw'][1:],[0,1]);self.assertEqual(r['brake_motor_ramp']['state'],'idle')
        old={k:v for k,v in CFG.items() if not k.startswith('brake_motor_')}
        c=self.make(cfg=old)
        c.step(self.obs(0),4.,0,0,.02)
        self.assertEqual(c.step(self.obs(.1,1),4.,.1,.1,.02)['raw'][1:],[0,1])

    def test_protective_faults_abort_ramp_permanently_and_preserve_first_stop_reason(self):
        for failure in ('sensor_or_path_lost','stale_speed','another_cmd_publisher','bag_replay_detected','clock_reversed'):
            c,start,_=self.ramp_start()
            now=start+.1
            observation=None if failure=='sensor_or_path_lost' else self.obs(now)
            speed_time=now-1 if failure=='stale_speed' else now
            fault=None if failure in ('sensor_or_path_lost','stale_speed') else failure
            r=c.step(observation,4.,speed_time,now,.02,fault)
            self.assertEqual(r['raw'][1:],[0,1]);self.assertEqual(r['reason'],'stop_row_braking')
            self.assertEqual(r['brake_motor_ramp']['state'],'cancelled')
            now+=.1
            self.assertEqual(c.step(self.obs(now),4.,now,now,.02)['raw'][1:],[0,1])

    def test_operator_stop_and_shutdown_abort_ramp(self):
        for reason in ('operator_stop','operator_interrupt','stdin_closed','operator_error'):
            c,start,_=self.ramp_start();c.stop(reason)
            r=c.step(self.obs(start+.1),4.,start+.1,start+.1,.02)
            self.assertEqual(r['raw'][1:],[0,1]);self.assertEqual(r['brake_motor_ramp']['cancel_reason'],reason)
        c,_,_=self.ramp_start()
        self.assertEqual(c.result(True,'shutdown')['raw'][1:],[0,1])
        self.assertEqual(c.brake_ramp_cancel_reason,'shutdown')

    def test_enabled_ramp_does_not_apply_to_initial_protective_stop_or_idle(self):
        c=self.make(cfg=dict(CFG,brake_motor_ramp_enabled=True))
        c.step(self.obs(0),4.,0,0,.02)
        self.assertEqual(c.step(None,4.,.1,.1,.02)['raw'][1:],[0,1])
        self.assertIsNone(c.brake_ramp_started)
        c=self.make(cfg=dict(CFG,brake_motor_ramp_enabled=True),phase='hold')
        self.assertEqual(c.step(self.obs(0),0.,0,0,.02)['raw'][1:],[0,1])

    def test_ramp_config_validation(self):
        for value in (0.,-1.,float('nan'),float('inf'),True,'1',None):
            with self.assertRaises(ValueError,msg=value):
                self.make(cfg=dict(CFG,brake_motor_ramp_enabled=True,brake_motor_ramp_35_to_zero_s=value))
        for value in (0,1,'false',None):
            with self.assertRaises(ValueError,msg=value):self.make(cfg=dict(CFG,brake_motor_ramp_enabled=value))

    def steering_brake(self, angle=17.01, reference=1., zero=0., **settings):
        cfg=dict(CFG,steering_zero_deg=zero,brake_steering_return_enabled=True,
                 brake_steering_full_left_to_zero_s=reference,**settings)
        c=self.make(cfg=cfg)
        c.step(self.obs(0),4.,0,0,.02)
        c.angle=math.radians(angle)
        before=c.result(False,'accelerate')
        onset=c.step(self.obs(.02,1.),4.,.02,.02,.02)
        return c,.02,before,onset

    def test_steering_return_both_sides_have_constant_rate_and_stop_at_zero(self):
        for initial in (17.01,-17.01,8.505,-8.505,2.,-2.,0.):
            with self.subTest(initial=initial):
                c,start,before,onset=self.steering_brake(initial)
                self.assertEqual(onset['raw'][0],before['raw'][0]);self.assertEqual(onset['raw'][1:],[0,1])
                for elapsed in (.02,.1,.25,.5,.9,1.,2.):
                    now=start+elapsed
                    r=c.step(self.obs(now,40.,y=-1),4.,now,now,.001)
                    remaining=max(0.,abs(initial)-17.01*elapsed)
                    expected=math.copysign(remaining,initial) if remaining else 0.
                    self.assertAlmostEqual(math.degrees(c.angle),expected)
                    self.assertAlmostEqual(r['raw'][0],-expected/17.01,places=6)
                    self.assertEqual(r['raw'][1:],[0,1]);self.assertEqual(r['reason'],'stop_row_braking')
                self.assertEqual(r['brake_steering_return']['state'],'completed')

    def test_steering_return_reference_time_scales_with_initial_angle_and_uses_elapsed_time(self):
        for reference,angle,duration in ((1.,8.505,.5),(.5,17.01,.5),(2.,-17.01,2.)):
            c,start,_,_=self.steering_brake(angle,reference)
            now=start+duration/2
            r=c.step(self.obs(now),4.,now,now,.001)
            self.assertAlmostEqual(math.degrees(c.angle),angle/2)
            self.assertAlmostEqual(r['brake_steering_return']['rate_degps'],17.01/reference)
            now=start+duration+.01
            r=c.step(self.obs(now),4.,now,now,.001)
            self.assertEqual(c.angle,0.);self.assertEqual(r['raw'],[0,0,1])

    def test_steering_return_anchors_to_saturated_command_and_keeps_calibrated_zero(self):
        for zero in (2.,-2.):
            c,start,before,onset=self.steering_brake(angle=100.,zero=zero)
            self.assertEqual(before['raw'][0],-1.);self.assertEqual(onset['raw'][0],-1.)
            self.assertAlmostEqual(onset['brake_steering_return']['start_deg'],17.01-zero)
            now=start+.5
            r=c.step(self.obs(now),4.,now,now,.02)
            board_angle=(17.01+zero)/2
            self.assertAlmostEqual(r['raw'][0],-board_angle/17.01,places=6)
            now=start+1.
            r=c.step(self.obs(now),4.,now,now,.02)
            self.assertEqual(c.angle,0.);self.assertAlmostEqual(r['raw'][0],-zero/17.01,places=6)
        c,start,_,_=self.steering_brake(angle=-100.,zero=2.)
        now=start+1.
        r=c.step(self.obs(now),4.,now,now,.02)
        self.assertAlmostEqual(math.degrees(c.angle),-4.)
        self.assertEqual(r['brake_steering_return']['state'],'active')

    def test_disabled_or_old_steering_return_config_keeps_last_angle(self):
        old={k:v for k,v in CFG.items() if not k.startswith('brake_steering_')}
        configs=[old]+[dict(CFG,brake_steering_full_left_to_zero_s=t) for t in (0.,-1.,float('nan'),'unused',None)]
        for cfg in configs:
            c=self.make(cfg=cfg);c.step(self.obs(0,y=1),4.,0,0,.02)
            held=c.result(False,'accelerate')['raw'][0]
            for now in (.1,.5,2.):
                r=c.step(self.obs(now,1.,y=-1),4.,now,now,.02)
                self.assertEqual(r['raw'][0],held);self.assertEqual(r['raw'][1:],[0,1])
                self.assertEqual(r['brake_steering_return']['state'],'idle')

    def test_steering_return_faults_freeze_last_command_and_never_resume(self):
        for fault in ('sensor_or_path_lost','stale_speed','another_cmd_publisher','bag_replay_detected','clock_reversed'):
            c,start,_,_=self.steering_brake()
            now=start+.1
            held=c.step(self.obs(now),4.,now,now,.02)['raw'][0]
            now=start+(.05 if fault=='clock_reversed' else .2)
            obs=None if fault=='sensor_or_path_lost' else self.obs(now)
            speed_time=now-1 if fault=='stale_speed' else now
            injected=None if fault in ('sensor_or_path_lost','stale_speed') else fault
            r=c.step(obs,4.,speed_time,now,.02,injected)
            self.assertEqual(r['raw'],[held,0,1]);self.assertEqual(r['reason'],'stop_row_braking')
            self.assertEqual(r['brake_steering_return']['state'],'cancelled')
            self.assertEqual(r['brake_steering_return']['cancel_reason'],
                             'sensor_or_path_lost' if fault=='stale_speed' else fault)
            r=c.step(self.obs(start+3),4.,start+3,start+3,.02)
            self.assertEqual(r['raw'],[held,0,1])

    def test_steering_return_operator_stop_and_shutdown_cancel_without_recentering(self):
        for reason in ('operator_stop','operator_interrupt','stdin_closed','operator_error','shutdown'):
            c,start,_,_=self.steering_brake()
            now=start+.1
            held=c.step(self.obs(now),4.,now,now,.02)['raw'][0]
            if reason!='shutdown':c.stop(reason)
            r=c.result(True,reason)
            self.assertEqual(r['raw'],[held,0,1])
            self.assertEqual(r['brake_steering_return']['state'],'cancelled')
            self.assertEqual(r['brake_steering_return']['cancel_reason'],reason)

    def test_steering_return_is_independent_of_motor_ramp(self):
        c,start,_,onset=self.steering_brake(reference=2.,brake_motor_ramp_enabled=True,
                                         max_accel_kphps=1750.)
        self.assertEqual(onset['target_kph'],35.)
        for elapsed,motor_kph,angle in ((.5,17.5,12.7575),(1.,0.,8.505),(2.,0.,0.)):
            now=start+elapsed
            r=c.step(self.obs(now),4.,now,now,.02)
            self.assertAlmostEqual(r['target_kph'],motor_kph)
            self.assertAlmostEqual(math.degrees(c.angle),angle);self.assertEqual(r['raw'][2],1)

    def test_steering_return_never_starts_on_protective_stop_or_idle(self):
        cfg=dict(CFG,brake_steering_return_enabled=True)
        c=self.make(cfg=cfg);before=c.step(self.obs(0,y=1),4.,0,0,.02)
        r=c.step(None,4.,.1,.1,.02)
        self.assertEqual(r['raw'][0],before['raw'][0]);self.assertEqual(r['raw'][1:],[0,1])
        self.assertEqual(r['brake_steering_return']['state'],'idle')
        c=self.make(cfg=cfg,phase='hold')
        r=c.step(self.obs(0),0.,0,0,.02)
        self.assertEqual(r['raw'],[0,0,1]);self.assertEqual(r['brake_steering_return']['state'],'idle')

    def test_steering_return_config_validation(self):
        for value in (0,1,'false',None):
            with self.assertRaises(ValueError,msg=value):self.make(cfg=dict(CFG,brake_steering_return_enabled=value))
        for value in (0.,-1.,float('nan'),float('inf'),True,'1',None,5e-324):
            with self.assertRaises(ValueError,msg=value):
                self.make(cfg=dict(CFG,brake_steering_return_enabled=True,brake_steering_full_left_to_zero_s=value))


if __name__=='__main__':unittest.main()
