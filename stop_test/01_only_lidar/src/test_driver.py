"""Real ROS wire test, only in a network-isolated temporary test container."""
import json
import math
import os
import queue
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray
from sensor_msgs.msg import PointCloud2
from nav_msgs.msg import Odometry
from run import Driver
from test_controller import CFG,SPEEDS


class DriverTest(unittest.TestCase):
    def test_gnss_confirmed_stop_prints_measured_peak_and_writes_report_once(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        directory=tempfile.TemporaryDirectory();driver=None
        try:
            driver=Driver(dict(CFG,prediction_url=''),SPEEDS,os.environ['TEST_CORE'],Path(directory.name))
            driver.timer.cancel();driver.logic.begin(0)
            messages=[];driver.say=messages.append
            start=time.monotonic();driver.started=start-2;driver.last_tick=start-.02
            for i in range(27):
                now=start+i*.05
                msg=Odometry();msg.header.frame_id='map';msg.header.stamp.sec=100+i
                msg.pose.pose.position.x=100.;msg.pose.pose.position.y=200.+min(i,10)*.4
                msg.twist.twist.linear.x=(10. if i==4 else 8.) if i<10 else 0.
                observation=dict(time=now,frame=i+1,path=[[2,0],[20,0]],ground='near_verified',
                    stop_state='confirmed' if i>=7 else 'none',stop_distance_m=1.,cones_lidar_m=[[-10.,1.,-1.]])
                with patch('run.time.monotonic',return_value=now):
                    driver.odom(msg);driver.observation=observation;driver.tick()
                    driver.telemetry.scan(observation)
                if i<20:self.assertFalse(driver.report_claimed)
            self.assertTrue(driver.report_claimed);driver.report_thread.join(timeout=2)
            report=json.loads((Path(directory.name)/'report.json').read_text())
            self.assertEqual(report['max_speed_kph'],36.)
            self.assertTrue(report['stop_confirmed']);self.assertGreaterEqual(report['confirmed_at']-report['stopped_since'],.5)
            self.assertEqual(len([m for m in messages if '최고 속도:' in m]),1)
            self.assertTrue(any('36.00' in m for m in messages))
            self.assertTrue(report['scans']);self.assertTrue(report['commands'])
            evidence=os.environ.get('STOP_TEST_REPORT_EVIDENCE')
            if evidence:(Path(evidence)/'driver-report.json').write_text(json.dumps(report,ensure_ascii=False)+'\n')
        finally:
            if driver is not None:driver.close()
            rclpy.shutdown();directory.cleanup()

    def test_shutdown_during_ramp_sends_zero_before_recording_cancellation(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        directory=tempfile.TemporaryDirectory();driver=None
        try:
            cfg=dict(CFG,prediction_url='',max_accel_kphps=1750.,brake_motor_ramp_enabled=True)
            driver=Driver(cfg,SPEEDS,os.environ['TEST_CORE'],Path(directory.name))
            driver.timer.cancel();driver.logic.begin(0)
            for now,distance in ((0.,None),(.02,1.)):
                obs=dict(time=now,frame=now,path=[[2,1],[20,1]],ground='near_verified',
                         stop_state='confirmed' if distance is not None else 'none',stop_distance_m=distance)
                result=driver.logic.step(obs,4.,now,now,.02)
            self.assertGreater(result['raw'][1],0);self.assertEqual(result['raw'][2],1)
            driver.last_ramp_state='active'
            calls=[]
            driver.publisher=Mock()
            driver.publisher.publish.side_effect=lambda msg:calls.append(list(msg.data))
            driver.event=lambda name,**data:calls.append((name,data))
            driver.close();driver=None
            self.assertEqual(len(calls),4)
            self.assertTrue(all(raw[1:]==[0,1] for raw in calls[:3]))
            self.assertEqual(calls[-1][0],'brake_motor_ramp_cancelled')
            self.assertEqual(calls[-1][1]['cancel_reason'],'shutdown')
        finally:
            if driver is not None:driver.close()
            rclpy.shutdown();directory.cleanup()

    def test_ramp_cmd_wire_logging_and_shutdown(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        directory=tempfile.TemporaryDirectory();driver=None;listener=None
        executor=SingleThreadedExecutor()
        try:
            cfg=dict(CFG,publish_cmd=True,prediction_url='',max_accel_kphps=1750.,
                     brake_motor_ramp_enabled=True,brake_motor_ramp_35_to_zero_s=1.)
            driver=Driver(cfg,SPEEDS,os.environ['TEST_CORE'],Path(directory.name))
            driver.timer.cancel();self.assertTrue(driver.logic.begin(0))
            listener=Node('stop_ramp_wire_listener');received=[]
            listener.create_subscription(Float32MultiArray,'/isolated/stop_test/cmd',lambda m:received.append(list(m.data)),10)
            executor.add_node(listener)
            deadline=time.monotonic()+1
            while driver.publisher.get_subscription_count()==0 and time.monotonic()<deadline:
                executor.spin_once(timeout_sec=.02)
            self.assertGreater(driver.publisher.get_subscription_count(),0)
            start=time.monotonic();driver.started=start-2;driver.last_tick=start-.02
            def tick(now,distance=None):
                driver.speed=4.;driver.speed_time=now;driver.last_log=0
                driver.observation=dict(time=now,frame=now,path=[[2,1],[20,1]],ground='near_verified',
                    stop_state='confirmed' if distance is not None else 'none',stop_distance_m=distance)
                with patch('run.time.monotonic',return_value=now):driver.tick()
                deadline=time.monotonic()+1;count=len(received)
                while len(received)==count and time.monotonic()<deadline:executor.spin_once(timeout_sec=.01)
                self.assertGreater(len(received),count)
                return received[-1]
            before=tick(start)
            self.assertGreater(before[1],0);self.assertEqual(before[2],0)
            onset=tick(start+.02,1.)
            self.assertEqual(onset[2],1);self.assertEqual(onset[:2],before[:2])
            half=tick(start+.52)
            self.assertAlmostEqual(half[1],onset[1]/2,places=6);self.assertEqual(half[2],1)
            self.assertEqual(tick(start+1.02)[1:],[0,1])
            driver.close();driver=None
            rows=[json.loads(l) for l in (Path(directory.name)/'commands.jsonl').read_text().splitlines()]
            events=[r.get('event') for r in rows]
            self.assertIn('brake_motor_ramp_active',events);self.assertIn('brake_motor_ramp_completed',events)
            samples=[r for r in rows if 'brake_motor_ramp' in r and 'time_monotonic' in r]
            self.assertTrue(any(r['brake_motor_ramp']['state']=='active' and r['raw'][1]>0 and r['raw'][2]==1 for r in samples))
        finally:
            if driver is not None:driver.close()
            if listener is not None:executor.remove_node(listener);listener.destroy_node()
            executor.shutdown();rclpy.shutdown();directory.cleanup()

    def test_ramp_blocks_operator_release_until_motor_command_is_zero(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        directory=tempfile.TemporaryDirectory();driver=None;inputs=queue.Queue()
        try:
            cfg=dict(CFG,prediction_url='',max_accel_kphps=1750.,
                     brake_motor_ramp_enabled=True,brake_motor_ramp_35_to_zero_s=1.)
            driver=Driver(cfg,SPEEDS,os.environ['TEST_CORE'],Path(directory.name))
            driver.timer.cancel();driver.logic.begin(0)
            def observation(now,distance=None):
                return dict(time=now,frame=now,path=[[2,0],[20,0]],ground='near_verified',
                    stop_state='confirmed' if distance is not None else 'none',stop_distance_m=distance)
            with driver.lock:
                now=time.monotonic()
                driver.logic.step(observation(now),0.,now,now,.02)
                driver.logic.step(observation(now+.02,1.),0.,now+.02,now+.02,.02)
                driver.speed=0.;driver.speed_time=now
            self.assertTrue(driver.logic.brake_motor_ramping)
            messages=[];driver.say=messages.append
            driver.inputs=inputs
            driver.operator=threading.Thread(target=driver.finish,daemon=True);driver.operator.start()
            inputs.put('\n')
            deadline=time.monotonic()+1
            while not any('감쇠 중' in m for m in messages) and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(any('감쇠 중' in m for m in messages));self.assertFalse(driver.releasing)
            inputs.put('q\n')
            deadline=time.monotonic()+1
            while driver.logic.brake_motor_ramping and time.monotonic()<deadline:time.sleep(.01)
            self.assertFalse(driver.logic.brake_motor_ramping);self.assertEqual(driver.logic.target,0.)
            self.assertEqual(driver.logic.brake_ramp_cancel_reason,'operator_stop')
            self.assertFalse(driver.releasing)
            inputs.put(None);driver.operator.join(timeout=1)
        finally:
            if driver is not None:driver.close()
            rclpy.shutdown();directory.cleanup()

    def test_steering_return_wire_logs_completion_and_shutdown_freezes_last_angle(self):
        for interrupted in (False,True):
            with self.subTest(interrupted=interrupted):
                rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
                directory=tempfile.TemporaryDirectory();driver=None;listener=None
                executor=SingleThreadedExecutor();received=[]
                try:
                    cfg=dict(CFG,publish_cmd=True,prediction_url='',steering_zero_deg=1.5,
                             brake_steering_return_enabled=True,brake_steering_full_left_to_zero_s=1.)
                    driver=Driver(cfg,SPEEDS,os.environ['TEST_CORE'],Path(directory.name))
                    driver.timer.cancel();driver.logic.begin(0)
                    listener=Node('stop_steering_return_wire_listener')
                    listener.create_subscription(Float32MultiArray,'/isolated/stop_test/cmd',
                                                 lambda msg:received.append(list(msg.data)),10)
                    executor.add_node(listener)
                    deadline=time.monotonic()+1
                    while driver.publisher.get_subscription_count()==0 and time.monotonic()<deadline:
                        executor.spin_once(timeout_sec=.02)
                    self.assertGreater(driver.publisher.get_subscription_count(),0)
                    start=time.monotonic();driver.started=start-2;driver.last_tick=start-.02
                    def tick(now,distance=None):
                        driver.speed=4.;driver.speed_time=now;driver.last_log=0
                        driver.observation=dict(time=now,frame=now,path=[[2,1],[20,1]],ground='near_verified',
                            stop_state='confirmed' if distance is not None else 'none',stop_distance_m=distance)
                        with patch('run.time.monotonic',return_value=now):driver.tick()
                        deadline=time.monotonic()+1;count=len(received)
                        while len(received)==count and time.monotonic()<deadline:executor.spin_once(timeout_sec=.01)
                        self.assertGreater(len(received),count)
                        return received[-1]
                    before=tick(start);onset=tick(start+.02,1.)
                    self.assertEqual(onset[0],before[0]);self.assertEqual(onset[1:],[0,1])
                    self.assertTrue(driver.logic.brake_steering_returning)
                    duration=abs(math.degrees(driver.logic.steering_return_initial))/driver.logic.steering_return_rate_degps
                    center=driver.logic.core.raw(0.,0.,True,cfg['steering_zero_deg'],cfg['wheel_diameter_m'])[0]
                    half=tick(start+.02+duration/2)
                    self.assertAlmostEqual(half[0],(onset[0]+center)/2,places=6)
                    self.assertEqual(half[1:],[0,1])
                    if not interrupted:
                        complete=tick(start+.03+duration)
                        self.assertAlmostEqual(complete[0],center,places=6)
                        self.assertFalse(driver.logic.brake_steering_returning)
                    driver.close();driver=None
                    rows=[json.loads(line) for line in (Path(directory.name)/'commands.jsonl').read_text().splitlines()]
                    events=[r.get('event') for r in rows]
                    self.assertIn('brake_steering_return_active',events)
                    self.assertIn('brake_steering_return_cancelled' if interrupted else 'brake_steering_return_completed',events)
                    if interrupted:
                        cancelled=next(r for r in rows if r.get('event')=='brake_steering_return_cancelled')
                        self.assertEqual(cancelled['cancel_reason'],'shutdown');self.assertEqual(cancelled['raw'],half)
                    evidence=os.environ.get('STOP_TEST_REPORT_EVIDENCE')
                    if evidence:
                        name='steering-return-cancelled' if interrupted else 'steering-return-completed'
                        (Path(evidence)/(name+'-commands.jsonl')).write_text((Path(directory.name)/'commands.jsonl').read_text())
                        (Path(evidence)/(name+'-wire.json')).write_text(json.dumps(received)+'\n')
                finally:
                    if driver is not None:driver.close()
                    if listener is not None:executor.remove_node(listener);listener.destroy_node()
                    executor.shutdown();rclpy.shutdown();directory.cleanup()

    def test_steering_return_blocks_release_and_operator_stop_freezes_angle(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        directory=tempfile.TemporaryDirectory();driver=None;inputs=queue.Queue()
        try:
            driver=Driver(dict(CFG,prediction_url='',brake_steering_return_enabled=True,
                               brake_steering_full_left_to_zero_s=10.),SPEEDS,os.environ['TEST_CORE'],Path(directory.name))
            driver.timer.cancel();driver.logic.begin(0)
            now=time.monotonic()
            obs=dict(time=now,frame=now,path=[[2,0],[20,0]],ground='near_verified',stop_state='none',stop_distance_m=None)
            driver.logic.step(obs,0.,now,now,.02);driver.logic.angle=math.radians(17.01)
            driver.logic.step(dict(obs,time=now+.02,frame=now+.02,stop_state='confirmed',stop_distance_m=1.),
                              0.,now+.02,now+.02,.02)
            held=driver.logic.angle;driver.speed=0.;driver.speed_time=now
            messages=[];driver.say=messages.append;driver.inputs=inputs
            driver.operator=threading.Thread(target=driver.finish,daemon=True);driver.operator.start()
            inputs.put('\n');deadline=time.monotonic()+1
            while not any('조향 영점 복귀 중' in m for m in messages) and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(any('조향 영점 복귀 중' in m for m in messages));self.assertFalse(driver.releasing)
            inputs.put('q\n');deadline=time.monotonic()+1
            while driver.logic.brake_steering_returning and time.monotonic()<deadline:time.sleep(.01)
            self.assertFalse(driver.logic.brake_steering_returning);self.assertEqual(driver.logic.angle,held)
            self.assertEqual(driver.logic.steering_return_cancel_reason,'operator_stop');self.assertFalse(driver.releasing)
            inputs.put(None);driver.operator.join(timeout=1)
        finally:
            inputs.put(None)
            if driver is not None:
                if driver.operator is not None:driver.operator.join(timeout=1)
                driver.close()
            rclpy.shutdown();directory.cleanup()

    def test_display_reports_recognition_then_braking_and_holds_first_reason(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        driver=None
        try:
            with tempfile.TemporaryDirectory() as directory:
                driver=Driver(dict(CFG,prediction_url=''),SPEEDS,os.environ['TEST_CORE'],Path(directory))
                self.assertTrue(driver.logic.begin(0))
                packets=[];driver.display.offer=packets.append
                driver.started=time.monotonic()-2
                for distance in (30.,2.,None):
                    now=time.monotonic();driver.last_log=0
                    driver.speed=4.;driver.speed_time=now
                    driver.observation=(dict(time=now,frame=now,path=[[2,0],[20,0]],ground='near_verified',
                        stop_state='confirmed',stop_distance_m=distance) if distance is not None else None)
                    driver.tick()
                self.assertFalse(packets[0]['brake']);self.assertFalse(packets[0]['publish_cmd'])
                self.assertEqual(packets[0]['drive']['stop_state'],'confirmed')
                self.assertEqual(packets[1]['drive']['reason'],'stop_row_braking')
                self.assertTrue(packets[1]['brake']);self.assertEqual(packets[1]['drive']['command_kph'],0)
                self.assertEqual(packets[2]['drive']['reason'],'stop_row_braking')
                self.assertEqual(packets[2]['drive']['stop_state'],'unavailable')
                self.assertEqual(packets[2]['drive']['brake_distance_m'],packets[1]['drive']['brake_distance_m'])
                self.assertIsNone(driver.publisher)
        finally:
            if driver is not None:driver.close()
            rclpy.shutdown()

    def test_disabled_has_no_cmd_publisher_enabled_sends_wire_and_stale_brakes(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        directory=tempfile.TemporaryDirectory();driver=None;listener=None
        executor=SingleThreadedExecutor()
        try:
            driver=Driver(dict(CFG,prediction_url=''),SPEEDS,os.environ['TEST_CORE'],Path(directory.name))
            self.assertIsNone(driver.publisher)
            msg=PointCloud2();msg.header.stamp.sec=1
            with driver.lock:
                driver.cloud(msg);old=driver.pending
                driver.cloud(msg);self.assertEqual(driver.pending,old)
            driver.close();driver=None
            driver=Driver(dict(CFG,publish_cmd=True,prediction_url=''),SPEEDS,os.environ['TEST_CORE'],Path(directory.name))
            self.assertTrue(driver.logic.begin(0))
            listener=Node('stop_cmd_wire_listener');received=[]
            subscription=listener.create_subscription(Float32MultiArray,'/isolated/stop_test/cmd',lambda m:received.append(list(m.data)),10)
            executor.add_node(driver);executor.add_node(listener)
            end=time.monotonic()+1.2
            while time.monotonic()<end:executor.spin_once(timeout_sec=.02)
            now=time.monotonic()
            with driver.lock:
                driver.observation=dict(time=now,frame=123,path=[[2,0],[20,0]],ground='near_verified',stop_state='none')
                driver.speed=0.;driver.speed_time=now
            end=time.monotonic()+.25
            while time.monotonic()<end:executor.spin_once(timeout_sec=.01)
            self.assertTrue(any(len(v)==3 and v[1]>0 and v[2]==0 for v in received),received)
            end=time.monotonic()+.4
            while time.monotonic()<end:executor.spin_once(timeout_sec=.01)
            self.assertEqual(received[-1][1:],[0,1])
            self.assertEqual(driver.logic.latched,'sensor_or_path_lost')
        finally:
            if driver is not None:executor.remove_node(driver);driver.close()
            if listener is not None:executor.remove_node(listener);listener.destroy_node()
            executor.shutdown();rclpy.shutdown();directory.cleanup()


    def test_path_loss_wire_holds_nineteen_scans_and_brakes_on_twentieth(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        directory=tempfile.TemporaryDirectory();driver=None;listener=None
        executor=SingleThreadedExecutor();received=[]
        try:
            driver=Driver(dict(CFG,publish_cmd=True,prediction_url=''),SPEEDS,
                          os.environ['TEST_CORE'],Path(directory.name))
            driver.timer.cancel();driver.logic.begin(0)
            listener=Node('stop_path_loss_wire_listener')
            listener.create_subscription(Float32MultiArray,'/isolated/stop_test/cmd',
                                         lambda msg:received.append(list(msg.data)),10)
            executor.add_node(listener)
            deadline=time.monotonic()+1
            while driver.publisher.get_subscription_count()==0 and time.monotonic()<deadline:
                executor.spin_once(timeout_sec=.02)
            self.assertGreater(driver.publisher.get_subscription_count(),0)
            start=time.monotonic();driver.started=start-2;driver.last_tick=start-.02
            def tick(now,frame,received_time,has_path):
                driver.speed=3.;driver.speed_time=now;driver.last_log=0
                driver.observation=dict(time=received_time,frame=frame,
                    path=[[2,1],[20,1]] if has_path else None,
                    ground='near_verified' if has_path else 'unchecked',stop_state='none')
                count=len(received)
                with patch('run.time.monotonic',return_value=now):driver.tick()
                deadline=time.monotonic()+1
                while len(received)==count and time.monotonic()<deadline:executor.spin_once(timeout_sec=.01)
                self.assertGreater(len(received),count)
                return received[-1]
            before=tick(start,0,start,True)
            for frame in range(1,21):
                now=start+frame*.1
                raw=tick(now,frame,now,False)
                self.assertEqual(driver.logic.path_missing_frames,frame)
                if frame<20:
                    self.assertEqual(raw,before)
                    self.assertEqual(tick(now+.02,frame,now,False),before)
                    self.assertEqual(driver.logic.path_missing_frames,frame)
                else:self.assertEqual(raw[1:],[0,1])
            self.assertEqual(tick(start+2.1,21,start+2.1,True)[1:],[0,1])
            rows=[json.loads(line) for line in (Path(directory.name)/'commands.jsonl').read_text().splitlines()]
            grace=[r for r in rows if r.get('reason')=='path_loss_grace']
            self.assertEqual({r['path_missing_frames'] for r in grace},set(range(1,20)))
            self.assertTrue(all(r['path_loss_stop_frames']==20 for r in grace))
            evidence=os.environ.get('STOP_TEST_REPORT_EVIDENCE')
            if evidence:
                (Path(evidence)/'path-loss-commands.jsonl').write_text((Path(directory.name)/'commands.jsonl').read_text())
                (Path(evidence)/'path-loss-wire.json').write_text(json.dumps(received)+'\n')
        finally:
            if driver is not None:driver.close()
            if listener is not None:executor.remove_node(listener);listener.destroy_node()
            executor.shutdown();rclpy.shutdown();directory.cleanup()

    def test_operator_flow_blind_start_stop_then_release_sends_zero_and_exits(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        directory=tempfile.TemporaryDirectory();driver=None;listener=None
        executor=SingleThreadedExecutor();inputs=queue.Queue();state=dict(frame=0,path=False,stop=None,speed=1.)
        try:
            driver=Driver(dict(CFG,publish_cmd=True,prediction_url=''),dict(SPEEDS,line_confirm_frames=3,blind_start_kph=10.),
                          os.environ['TEST_CORE'],Path(directory.name),inputs)
            listener=Node('stop_operator_wire_listener');received=[]
            listener.create_subscription(Float32MultiArray,'/isolated/stop_test/cmd',lambda m:received.append(list(m.data)),10)
            executor.add_node(driver);executor.add_node(listener)
            def spin(seconds,until=None):
                end=time.monotonic()+seconds
                while time.monotonic()<end and not (until and until()):
                    now=time.monotonic();state['frame']+=1
                    with driver.lock:
                        driver.observation=dict(time=now,frame=state['frame'],
                            path=[[2,0],[20,0]] if state['path'] else None,
                            ground='near_verified' if state['path'] else 'unchecked',
                            stop_state='confirmed' if state['stop'] is not None else 'none',stop_distance_m=state['stop'] or 0)
                        driver.speed=state['speed'];driver.speed_time=now
                    executor.spin_once(timeout_sec=.02)
            spin(1.2);self.assertTrue(received and all(v[1:]==[0,1] for v in received))
            inputs.put('\n');spin(1.4)
            self.assertEqual(driver.logic.phase,'blind');self.assertGreater(received[-1][1],0);self.assertEqual(received[-1][2],0)
            spin(1.);self.assertAlmostEqual(driver.logic.target*3.6,10.)
            state['path']=True;spin(.5,lambda:driver.logic.phase=='drive');self.assertEqual(driver.logic.phase,'drive')
            state['stop']=1.;spin(.3,lambda:driver.logic.latched is not None)
            self.assertEqual(driver.logic.latched,'stop_row_braking');spin(.2);self.assertEqual(received[-1][1:],[0,1])
            state['speed']=0.;inputs.put('\n');spin(.5);self.assertTrue(driver.releasing)
            self.assertEqual(received[-1],[0.,0.,0.])
            spin(2.5,driver.exit.is_set);self.assertTrue(driver.exit.is_set());self.assertTrue(driver.released)
            events=[json.loads(l).get('event') for l in (Path(directory.name)/'commands.jsonl').read_text().splitlines()]
            for name in ('start_enter','lines_missing','blind_start','lines_confirmed','stopped','release','exit'):
                self.assertIn(name,events)
        finally:
            if driver is not None:executor.remove_node(driver);driver.close()
            if listener is not None:executor.remove_node(listener);listener.destroy_node()
            executor.shutdown();rclpy.shutdown();directory.cleanup()

    def test_real_start_gnss_wire_ignores_readiness_and_enters_drive_directly(self):
        for lines in (True,False):
            with self.subTest(lines=lines):
                rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd',
                                '-r','/gnss/odom:=/isolated/stop_test/odom'])
                directory=tempfile.TemporaryDirectory();driver=None;peer=None
                executor=SingleThreadedExecutor();inputs=queue.Queue();received=[]
                state=dict(frame=0,speed=1.,variance=1e12,stop=False,cloud=False)
                try:
                    speeds=dict(SPEEDS,test_mode=False,startup_speed_kph=5.,line_confirm_frames=3,
                                blind_start_timeout_s=.5)
                    driver=Driver(dict(CFG,publish_cmd=True,prediction_url=''),speeds,
                                  os.environ['TEST_CORE'],Path(directory.name),inputs)
                    driver.started=time.monotonic()-2
                    peer=Node('stop_real_start_wire_peer')
                    odom=peer.create_publisher(Odometry,'/gnss/odom',10)
                    peer.create_subscription(Float32MultiArray,'/cmd',lambda m:received.append(list(m.data)),10)
                    executor.add_node(driver);executor.add_node(peer)
                    def spin(seconds,until=None):
                        end=time.monotonic()+seconds
                        while time.monotonic()<end and not (until and until()):
                            now=time.monotonic();state['frame']+=1
                            msg=Odometry();msg.header.frame_id='map';msg.child_frame_id='base_link'
                            msg.header.stamp.sec=100+state['frame']
                            msg.twist.twist.linear.x=state['speed'];msg.twist.covariance[0]=state['variance']
                            odom.publish(msg)
                            with driver.lock:
                                driver.observation=dict(time=now,frame=state['frame'],
                                    path=[[2,0],[20,0]] if lines else None,
                                    ground='near_verified' if lines else 'unchecked',
                                    stop_state='confirmed' if state['stop'] else 'none',stop_distance_m=1.) if state['cloud'] else None
                            executor.spin_once(timeout_sec=.02)
                    # Creep is sent without lidar or valid GNSS, but unavailable
                    # positive speed cannot trigger normal acceleration.
                    spin(.4)
                    self.assertEqual(driver.logic.phase,'hold');self.assertTrue(driver.logic.startup_commanded)
                    expected=driver.logic.core.raw(0,5/3.6,False,CFG['steering_zero_deg'],CFG['wheel_diameter_m'])
                    self.assertTrue(received and all(v==expected for v in received))
                    state.update(speed=0.,variance=.01);spin(.15)
                    self.assertEqual(received[-1],expected);self.assertEqual(driver.logic.phase,'hold')
                    # Enter and stationary noise are not start signals in real mode.
                    inputs.put('\n');state['speed']=.05;spin(.15)
                    self.assertEqual(driver.logic.phase,'hold');self.assertEqual(driver.logic.startup_motion_count,0)
                    state.update(speed=1.,cloud=lines);spin(.5,lambda:driver.logic.phase!='hold')
                    self.assertEqual(driver.logic.phase,'drive')
                    if lines:
                        spin(.15)
                        self.assertTrue(any(v[1]>expected[1] and v[2]==0 for v in received))
                        state['stop']=True
                    spin(.8,lambda:driver.logic.latched is not None)
                    self.assertEqual(driver.logic.latched,'stop_row_braking' if lines else 'sensor_or_path_lost')
                    count=len(received);spin(.15)
                    self.assertGreater(len(received),count);self.assertEqual(received[-1][1:],[0,1])
                    events=[json.loads(l).get('event') for l in (Path(directory.name)/'commands.jsonl').read_text().splitlines()]
                    self.assertEqual(events.count('start_motion'),1);self.assertNotIn('start_enter',events)
                    self.assertIn('drive_start',events);self.assertNotIn('blind_start',events)
                    evidence=os.environ.get('STOP_TEST_REPORT_EVIDENCE')
                    if evidence:
                        name='real-start-with-path' if lines else 'real-start-no-path'
                        (Path(evidence)/(name+'-commands.jsonl')).write_text((Path(directory.name)/'commands.jsonl').read_text())
                        (Path(evidence)/(name+'-wire.json')).write_text(json.dumps(received)+'\n')
                    inputs.put(None);driver.operator.join(timeout=1)
                    self.assertTrue(driver.exit.is_set());self.assertFalse(driver.released)
                finally:
                    inputs.put(None)
                    if driver is not None:
                        if driver.operator is not None:driver.operator.join(timeout=1)
                        executor.remove_node(driver);driver.close()
                    if peer is not None:executor.remove_node(peer);peer.destroy_node()
                    executor.shutdown();rclpy.shutdown();directory.cleanup()

    def test_operator_q_cancels_and_moving_vehicle_blocks_release(self):
        rclpy.init(args=['--ros-args','-r','/cmd:=/isolated/stop_test/cmd'])
        directory=tempfile.TemporaryDirectory();driver=None;inputs=queue.Queue()
        try:
            driver=Driver(dict(CFG,prediction_url=''),SPEEDS,os.environ['TEST_CORE'],Path(directory.name),inputs)
            inputs.put('q\n')
            deadline=time.monotonic()+1
            while driver.logic.latched is None and time.monotonic()<deadline:time.sleep(.02)
            self.assertEqual(driver.logic.latched,'operator_cancel');self.assertEqual(driver.logic.phase,'hold')
            with driver.lock:driver.speed=2.;driver.speed_time=time.monotonic()+5
            inputs.put('\n');time.sleep(.4);self.assertFalse(driver.releasing)
            inputs.put(None);driver.operator.join(timeout=1)
            self.assertTrue(driver.exit.is_set());self.assertFalse(driver.released)
        finally:
            if driver is not None:driver.close()
            rclpy.shutdown();directory.cleanup()


if __name__=='__main__':unittest.main()
