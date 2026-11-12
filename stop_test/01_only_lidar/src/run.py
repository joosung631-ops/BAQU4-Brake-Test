#!/usr/bin/env python3
"""Explicitly launched standalone live controller; never started by dashboard.

Test flow: Enter -> 1 s -> drive (lines confirmed) or automatic straight creep.
Real flow: low-speed command -> GNSS movement detection -> normal acceleration.
Every stop holds the brake until the
operator presses Enter, then 0,0,0 is published for 2 s before exit.
"""
import argparse
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
import uuid

ROOT=Path(os.environ.get('STOP_TEST_REPO_ROOT',Path(__file__).resolve().parents[3]))
STOP=ROOT/'stop_test' if (ROOT/'stop_test/01_only_lidar').exists() else ROOT
sys.path.insert(0,os.environ.get('STOP_TEST_LIDAR_PARENT',str(STOP/'src/lidar_cone')))
sys.path.insert(0,os.environ.get('STOP_TEST_VENDOR',str(STOP/'01_only_lidar/vendor')))
try:import tomllib
except ImportError:import tomli as tomllib
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Float32MultiArray

from lidar_cone.pointcloud import decode_cloud
from lidar_cone.detector import ConeDetector,DetectorConfig
from lidar_cone.course_lines import extract_course_lines
from lidar_cone.stop_row import detect_stop_row,StopRowTracker
from controller import Core,Controller
from display import PredictionSender
from telemetry import RunTelemetry,write_job

REASONS=dict(stop_row_braking='정지열 제동',sensor_or_path_lost='센서/경로 소실 보호정지',
             path_loss_grace='경로 재검출 대기 (직전 명령 유지)',
             invalid_pursuit='추종 계산 실패',another_cmd_publisher='다른 /cmd 발행자 감지',
             bag_replay_detected='bag 재생 감지',clock_reversed='시계 역행',
             blind_start_timeout='강제 직진 시간 초과 (선 미검출)',blind_start_sensor_lost='강제 직진 중 센서 소실',
             operator_cancel='운영자 출발 취소',operator_stop='운영자 정지 (q)',operator_interrupt='Ctrl-C 정지',
             stdin_closed='터미널 입력 종료')


class Driver(Node):
    def __init__(self, cfg, speeds, library, log_dir, inputs=None):
        super().__init__('stop_test_only_lidar_driver')
        self.cfg=cfg;self.logic=Controller(Core(library),speeds,cfg)
        self.lock=threading.RLock();self.done=threading.Event()
        # Operator flow: None disables it (tests drive self.logic directly).
        self.inputs=inputs;self.interrupted=False;self.releasing=False;self.released=False
        self.exit=threading.Event();self.log_lock=threading.Lock()
        self.pending=None;self.observation=None;self.speed=None;self.speed_time=None
        self.last_cloud_stamp=0;self.last_odom_stamp=0
        self.telemetry=RunTelemetry(cfg['sensor_timeout_s'])
        self.report_claimed=False;self.report_thread=None;self.report_path=log_dir/'report.json'
        self.tracker=StopRowTracker();self.perception_error=None
        self.detector=ConeDetector(DetectorConfig(x_min=-45.,range_max=48.))
        self.publisher=self.create_publisher(Float32MultiArray,'/cmd',1) if cfg['publish_cmd'] else None
        self.subscription=self.create_subscription(PointCloud2,'/lidar/points',self.cloud,qos_profile_sensor_data)
        self.odom_subscription=self.create_subscription(Odometry,'/gnss/odom',self.odom,qos_profile_sensor_data)
        self.started=self.last_tick=time.monotonic();self.last_log=0.
        self.last_ramp_state='idle'
        self.last_steering_return_state='idle'
        self.log=(log_dir/'commands.jsonl').open('a',buffering=1)
        self.log.write(json.dumps(dict(kind='settings',drive=cfg,speeds=speeds))+'\n')
        self.worker=threading.Thread(target=self.perceive,daemon=True);self.worker.start()
        self.timer=self.create_timer(.02,self.tick)
        self.display=PredictionSender(cfg.get('prediction_url',''))
        self.display_session=uuid.uuid4().hex;self.display_seq=0
        self.get_logger().info('publish_cmd='+str(cfg['publish_cmd'])+'; live sensors only; restart required after a latched stop')
        self.operator=None
        if inputs is not None:
            self.operator=threading.Thread(target=self.operate,daemon=True);self.operator.start()

    def event(self, name, **data):
        with self.log_lock:self.log.write(json.dumps(dict(kind='operator',event=name,time_monotonic=time.monotonic(),**data))+'\n')

    def say(self, text):
        print('[stop_test] '+text,flush=True)

    def ask(self, finishing=False):
        """Next input line; None on EOF, or (before finishing) on a stop/Ctrl-C."""
        while True:
            if not finishing:
                with self.lock:
                    if self.interrupted:self.logic.stop('operator_interrupt')
                    if self.logic.latched:return None
            try:line=self.inputs.get(timeout=.1)
            except queue.Empty:continue
            if line is None:
                with self.lock:self.logic.stop('stdin_closed')
                return None
            return line.strip()

    def operate(self):
        try:self.flow()
        except Exception as error:
            self.event('operator_error',error=str(error))
            with self.lock:self.logic.stop('operator_error')
            self.exit.set()

    def flow(self):
        s=self.logic.speeds;mock='' if self.publisher else ' [모의 실행: publish_cmd=false, /cmd 미발행]'
        if self.logic.test_mode:
            self.say('준비 완료'+mock+'. 차량 주변과 ASMS AUTO를 확인한 뒤 엔터를 누르면 1초 뒤 시작합니다. (q+엔터: 종료)')
            line=self.ask()
            if line=='q':
                with self.lock:self.logic.stop('operator_cancel')
            if line is None or line=='q':return self.finish()
            self.event('start_enter');self.say('1초 후 시작합니다.')
            deadline=time.monotonic()+1
            while time.monotonic()<deadline:
                with self.lock:
                    if self.interrupted:self.logic.stop('operator_interrupt')
                    latched=self.logic.latched
                if latched:return self.finish()
                time.sleep(.02)
        else:
            self.event('startup_wait_motion',target_kph=self.logic.startup_speed_kph)
            self.say(f'준비 완료{mock}. {self.logic.startup_speed_kph:g}km/h 전진 명령 전송 · GNSS 이동 감지 후 자동 시작합니다. (q+엔터: 종료)')
            while True:
                with self.lock:
                    if self.interrupted:self.logic.stop('operator_interrupt')
                    latched=self.logic.latched
                    detected=self.logic.startup_motion_count>=3
                if latched:return self.finish()
                if detected:break
                try:line=self.inputs.get(timeout=.02)
                except queue.Empty:continue
                if line is None or line.strip()=='q':
                    with self.lock:self.logic.stop('stdin_closed' if line is None else 'operator_cancel')
                    return self.finish()
            self.event('start_motion');self.say('GNSS 이동 확인 → 자동 시작')
        with self.lock:
            started=(not self.logic.test_mode or self.logic.lines_confirmed()) and self.logic.begin(time.monotonic())
        if started:
            self.event('drive_start');self.say('선 확인됨 → 주행 시작' if self.logic.test_mode else '이동 확인됨 → 정상 가속 시작')
        elif s['blind_start_kph']>0:
            self.event('lines_missing',lines=self.logic.lines)
            self.say(f"선 미검출 (연속 {s['line_confirm_frames']}프레임 미확인). 추가 엔터 없이 {s['blind_start_kph']:g}km/h로 강제 직진합니다. "
                     f"{s['blind_start_timeout_s']:g}초 안에 선을 확인하지 못하면 정지합니다.")
            with self.lock:
                blind=not self.logic.lines_confirmed();started=self.logic.begin(time.monotonic(),blind)
            if not started:return self.finish()
            self.event('blind_start' if blind else 'drive_start')
            self.say(f"강제 직진 시작 ({s['blind_start_kph']:g}km/h)" if blind else '선 확인됨 → 주행 시작')
        else:
            with self.lock:self.logic.begin(time.monotonic())
            self.event('drive_start');self.say('선 미검출, 강제 직진 꺼짐(blind_start_kph=0) → 선 확인 후 자동 출발')
        self.say('주행 중. q+엔터: 즉시 정지')
        with self.lock:phase=self.logic.phase
        while True:
            with self.lock:
                if self.interrupted:self.logic.stop('operator_interrupt')
                latched,current=self.logic.latched,self.logic.phase
            if current!=phase:
                if phase=='blind':self.event('lines_confirmed');self.say('선 확인됨 → 가속 시작')
                phase=current
            if latched:break
            try:line=self.inputs.get(timeout=.1)
            except queue.Empty:continue
            if line is None or line.strip()=='q':
                with self.lock:self.logic.stop('stdin_closed' if line is None else 'operator_stop')
        self.finish()

    def finish(self):
        with self.lock:
            reason=self.logic.latched;blind=self.logic.blind_started is not None
            elapsed=time.monotonic()-self.logic.blind_started if blind else 0;distance=self.logic.blind_distance
        detail=''
        if reason=='blind_start_timeout':detail=f' ({elapsed:.1f}초, 이동 약 {distance:.1f}m 동안 선 미확인)'
        self.event('stopped',reason=reason);self.say('정지: '+REASONS.get(reason,str(reason))+detail+' · 브레이크 유지 중')
        if reason=='stdin_closed':
            self.say('터미널 입력이 없어 브레이크를 유지한 채 종료합니다.');self.exit.set();return
        while True:
            self.say('엔터: /cmd로 0,0,0을 보내 브레이크를 풀고 2초 뒤 종료합니다. (Ctrl-C: 브레이크 유지한 채 즉시 종료)')
            line=self.ask(finishing=True)
            if line is None:
                self.say('터미널 입력이 없어 브레이크를 유지한 채 종료합니다.');self.exit.set();return
            if line=='q':
                with self.lock:self.logic.stop('operator_stop')
                self.event('operator_stop');self.say('모터 명령 0 · 브레이크 유지 중');continue
            with self.lock:
                speed,speed_time=self.speed,self.speed_time
                ramping=self.logic.brake_motor_ramping
                steering_returning=self.logic.brake_steering_returning
            if ramping:
                self.say('모터 명령 감쇠 중입니다. 모터 명령이 0이 된 뒤 다시 엔터를 누르세요.');continue
            if steering_returning:
                self.say('조향 영점 복귀 중입니다. 복귀 완료 뒤 다시 엔터를 누르세요.');continue
            known=speed is not None and speed_time is not None and time.monotonic()-speed_time<=self.cfg['sensor_timeout_s']
            if known and speed>.5:
                self.say(f'차량이 아직 움직입니다 ({speed*3.6:.1f}km/h). 정지 후 다시 엔터를 누르세요.');continue
            if not known:self.say('GNSS 속도 확인 불가: 차량 정지를 육안으로 확인했다고 보고 진행합니다.')
            break
        with self.lock:self.releasing=True
        self.event('release',speed_known=known);self.say('0,0,0 전송 중 (브레이크 해제)... 2초 후 종료')
        time.sleep(2)
        self.released=True;self.event('exit');self.exit.set()

    def cloud(self, msg):
        stamp=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
        with self.lock:
            if stamp<=self.last_cloud_stamp:return
            self.last_cloud_stamp=stamp;self.pending=(msg,time.monotonic())

    def odom(self, msg):
        speed=math.hypot(msg.twist.twist.linear.x,msg.twist.twist.linear.y)
        stamp=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
        with self.lock:
            if stamp<=self.last_odom_stamp:return
            self.last_odom_stamp=stamp
            self.speed=speed if math.isfinite(speed) and msg.twist.twist.linear.x>=-.3 else None
            self.speed_time=time.monotonic()
            speed_ok=math.isfinite(msg.twist.covariance[0]) and 0<=msg.twist.covariance[0]<1e8
            # Real start must not accept unavailable GNSS speed as movement.
            if not self.logic.test_mode and self.logic.phase=='hold' and not speed_ok:self.speed=None
            p=msg.pose.pose.position
            position=([p.x,p.y] if all(math.isfinite(v) for v in (p.x,p.y)) and
                all(math.isfinite(msg.pose.covariance[i]) and 0<=msg.pose.covariance[i]<1e8 for i in (0,7)) else None)
            self.telemetry.odom(self.speed_time,stamp,self.speed if speed_ok else None,
                                position,msg.header.frame_id)

    def perceive(self):
        while not self.done.wait(.005):
            with self.lock:
                pending,self.pending=self.pending,None
                speed,speed_time=self.speed,self.speed_time
            if pending is None:continue
            msg,received=pending
            try:
                if msg.header.frame_id!='os_lidar':raise ValueError('Expected os_lidar frame')
                xyz,attrs=decode_cloud(msg);frame=self.detector.detect(xyz,attrs)
                course=extract_course_lines([c.center for c in frame.cones],frame.plane)
                row=detect_stop_row(frame.roi_points,frame.plane,course)
                stamp=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
                row=self.tracker.update(row,received,stamp or received,
                    speed if speed_time is not None and abs(received-speed_time)<=.3 else None)
                path=None
                if course.get('state')=='paired' and 'center' in course['lines']:
                    xyz=np.asarray(course['lines']['center']['points_cm']).reshape(2,3)/100
                    # Explicit nominal sensor-to-rear-axle transform, not a TF lookup.
                    xy=-xyz[:,:2]
                    yaw=math.radians(self.cfg['lidar_yaw_offset_deg'])
                    rotation=np.array([[math.cos(yaw),-math.sin(yaw)],[math.sin(yaw),math.cos(yaw)]])
                    path=(xy@rotation.T+[self.cfg['lidar_x_m'],self.cfg['lidar_y_m']]).tolist()
                observation=dict(time=received,frame=stamp or received,path=path,ground=row['ground'],
                                 stop_state=row['state'],stop_distance_m=row.get('distance_cm',0)/100,
                                 cones_lidar_m=[c.center.tolist() for c in frame.cones])
                with self.lock:
                    self.observation=observation;self.perception_error=None
                    self.telemetry.scan(observation)
            except Exception as error:
                with self.lock:self.observation=None;self.perception_error=str(error)

    def tick(self):
        now=time.monotonic();dt=now-self.last_tick;self.last_tick=now
        with self.lock:
            fault=None
            # Recorded topics must not drive hardware. Graph discovery is given
            # one second at startup, then conflicts/replay latch a stop.
            if now-self.started<1:return
            if self.publisher and self.count_publishers('/cmd')>1:fault='another_cmd_publisher'
            if any(p.node_name.startswith(('rosbag2_player','dashboard_bag_player_'))
                   for topic in ('/lidar/points','/gnss/odom') for p in self.get_publishers_info_by_topic(topic)):
                fault='bag_replay_detected'
            observation,speed,speed_time=self.observation,self.speed,self.speed_time
            if self.releasing:
                # Operator-confirmed release after a stop: explicit 0,0,0 until exit.
                result=dict(self.logic.result(True,'operator_release'),raw=[0.,0.,0.],brake=False)
            else:
                result=self.logic.step(observation,speed,speed_time,now,dt,fault)
        if self.publisher:self.publisher.publish(Float32MultiArray(data=result['raw']))
        report=None
        with self.lock:
            if self.logic.phase!='hold' and not self.report_claimed:
                self.telemetry.start(now)
                self.telemetry.command(now,result,self.publisher is not None)
                if self.telemetry.stopped(now):
                    report=self.telemetry.snapshot(now,self.cfg,self.logic.speeds,self.logic.latched)
                    self.report_claimed=True
        if report is not None:
            self.report_thread=threading.Thread(target=self.save_report,args=(report,),daemon=True)
            self.report_thread.start()
        ramp=result['brake_motor_ramp']
        if ramp['state']!=self.last_ramp_state:
            self.event('brake_motor_ramp_'+ramp['state'],**ramp,target_kph=result['target_kph'],raw=result['raw'])
            self.last_ramp_state=ramp['state']
        steering_return=result['brake_steering_return']
        if steering_return['state']!=self.last_steering_return_state:
            self.event('brake_steering_return_'+steering_return['state'],**steering_return,raw=result['raw'])
            self.last_steering_return_state=steering_return['state']
        if now-self.last_log>=.1:
            with self.log_lock:
                self.log.write(json.dumps(dict(time_monotonic=now,**result,perception_error=self.perception_error))+'\n')
            self.last_log=now
            self.display_seq+=1
            speed_fresh=(speed_time is not None and 0<=now-speed_time<=self.cfg['sensor_timeout_s']
                         and speed is not None)
            fresh=(observation is not None and 0<=now-observation['time']<=self.cfg['sensor_timeout_s'] and speed_fresh)
            goal=(self.logic.speeds['high_speed' if self.logic.speeds['use_high_speed'] else 'low_speed']
                  if result['reached_max_speed'] else self.logic.speeds['max_speed'])
            self.display.offer(dict(session=self.display_session,seq=self.display_seq,
                angle_deg=-result['raw'][0]*17.01-self.cfg['steering_zero_deg'],
                speed_mps=speed if speed_fresh else None,brake=result['brake'],publish_cmd=self.publisher is not None,
                drive=dict(reason=result['reason'],command_kph=result['target_kph'],goal_kph=goal,
                    max_speed_kph=self.logic.speeds['max_speed'],reached_max_speed=result['reached_max_speed'],
                    stop_state=observation.get('stop_state','none') if fresh else 'unavailable',
                    stop_distance_m=result['stop_distance_m'],brake_distance_m=result['brake_distance_m'],
                    accelerating=bool(not result['brake'] and speed_fresh and result['target_kph']>speed*3.6+.5)),
                sensors_fresh=fresh,wheelbase_m=1.328,width_m=1.280,
                cloud_stamp_s=observation['frame']/1e9 if observation is not None else 0.,
                lidar_x_m=self.cfg['lidar_x_m'],lidar_y_m=self.cfg['lidar_y_m'],
                yaw_deg=self.cfg['lidar_yaw_offset_deg']))

    def save_report(self, report):
        try:
            self.say(f"완전 정지 확인 · 최고 속도: {report['max_speed_kph']:.2f} km/h (GNSS)")
            write_job(self.report_path,report)
            self.say('주행 그래프 생성 요청 완료 · 브레이크 유지 중')
        except Exception as error:
            self.say('주행 보고서 저장 실패: '+str(error))

    def close(self):
        self.timer.cancel();self.done.set()
        with self.lock:
            if not self.released:self.logic.stop('shutdown')
            result=self.logic.result(True,'shutdown')
        if self.publisher and rclpy.ok():
            # Brake on every exit except the operator-confirmed release.
            raw=[0.,0.,0.] if self.released else result['raw']
            for _ in range(3):self.publisher.publish(Float32MultiArray(data=raw));time.sleep(.02)
        if result['brake_motor_ramp']['state']!=self.last_ramp_state:
            self.event('brake_motor_ramp_'+result['brake_motor_ramp']['state'],
                       **result['brake_motor_ramp'],target_kph=result['target_kph'],raw=result['raw'])
        if result['brake_steering_return']['state']!=self.last_steering_return_state:
            self.event('brake_steering_return_'+result['brake_steering_return']['state'],
                       **result['brake_steering_return'],raw=result['raw'])
        self.worker.join(timeout=2)
        if self.report_thread is not None:self.report_thread.join(timeout=2)
        self.display.close()
        self.log.close();self.destroy_node()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--library',required=True)
    parser.add_argument('--config',type=Path,default=STOP/'01_only_lidar/config.toml')
    parser.add_argument('--speeds',type=Path,default=STOP/'config.toml')
    parser.add_argument('--log-dir',type=Path,required=True)
    args=parser.parse_args()
    cfg=tomllib.loads(args.config.read_text());speeds=tomllib.loads(args.speeds.read_text())
    args.log_dir.mkdir(parents=True,exist_ok=True)
    (args.log_dir/'config.toml').write_text(args.config.read_text())
    (args.log_dir/'speeds.toml').write_text(args.speeds.read_text())
    # Keep the ROS context alive long enough to send stop on Ctrl-C/SIGTERM.
    # First Ctrl-C stops and goes to the operator release prompt; a second one
    # (or SIGTERM) exits at once while braking.
    import signal
    from rclpy.signals import SignalHandlerOptions
    node=None
    def terminate(*_):raise KeyboardInterrupt
    def interrupt(*_):
        if node is None or node.operator is None or node.interrupted or node.logic.latched:raise KeyboardInterrupt
        node.interrupted=True
    signal.signal(signal.SIGTERM,terminate);signal.signal(signal.SIGINT,interrupt)
    inputs=queue.Queue()
    def read_stdin():
        while line:=sys.stdin.readline():inputs.put(line)
        inputs.put(None)
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    try:
        node=Driver(cfg,speeds,args.library,args.log_dir,inputs)
        threading.Thread(target=read_stdin,daemon=True).start()
        while rclpy.ok() and not node.exit.is_set():rclpy.spin_once(node,timeout_sec=.05)
    except KeyboardInterrupt:pass
    finally:
        if node is not None:node.close()
        if rclpy.ok():rclpy.shutdown()


if __name__=='__main__':main()
