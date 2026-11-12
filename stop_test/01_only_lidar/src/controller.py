"""ROS-free decisions. Reuses the existing C++ tracking and raw conversion."""
import ctypes
import math
from pathlib import Path

import numpy as np


class Core:
    def __init__(self, library):
        self.lib=ctypes.CDLL(str(Path(library).resolve()))
        double=ctypes.c_double
        self.lib.stop_pp.argtypes=[ctypes.POINTER(double),ctypes.c_int,double,ctypes.POINTER(double)]
        self.lib.stop_pp.restype=ctypes.c_int
        self.lib.stop_raw.argtypes=[double,double,ctypes.c_int,double,double,ctypes.POINTER(ctypes.c_float)]
        self.lib.stop_raw.restype=None

    def steering(self, path, speed):
        points=np.ascontiguousarray(path,dtype=np.float64)
        if points.ndim!=2 or points.shape[1]!=2 or len(points)<2 or not np.isfinite(points).all():
            return None
        angle=ctypes.c_double()
        ok=self.lib.stop_pp(points.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),len(points),speed,ctypes.byref(angle))
        return angle.value if ok else None

    def raw(self, angle, speed, brake, zero, diameter):
        values=(ctypes.c_float*3)()
        self.lib.stop_raw(angle,speed,int(brake),zero,diameter,values)
        return list(values)


class Controller:
    def __init__(self, core, speeds, cfg):
        self.core,self.speeds,self.cfg=core,speeds,cfg
        for name in ('max_speed','high_speed','low_speed'):
            value=speeds[name]
            if isinstance(value,bool) or not math.isfinite(value) or not 0<value<=50:
                raise ValueError('Invalid '+name)
        if type(speeds['use_high_speed']) is not bool or type(cfg['publish_cmd']) is not bool:
            raise ValueError('Mode flags must be bool')
        self.test_mode=speeds.get('test_mode',True)
        self.startup_speed_kph=speeds.get('startup_speed_kph',5.)
        if type(self.test_mode) is not bool:raise ValueError('Invalid test_mode')
        if (type(self.startup_speed_kph) not in (int,float) or not math.isfinite(self.startup_speed_kph)
                or not 0<self.startup_speed_kph<=10):raise ValueError('Invalid startup_speed_kph')
        self.path_loss_stop_frames=cfg.get('path_loss_stop_frames',20)
        if type(self.path_loss_stop_frames) is not int or self.path_loss_stop_frames<1:
            raise ValueError('Invalid path_loss_stop_frames')
        self.brake_ramp_enabled=cfg.get('brake_motor_ramp_enabled',False)
        if type(self.brake_ramp_enabled) is not bool:
            raise ValueError('Invalid brake_motor_ramp_enabled')
        self.brake_ramp_time=cfg.get('brake_motor_ramp_35_to_zero_s',1.)
        if self.brake_ramp_enabled and (type(self.brake_ramp_time) not in (int,float) or
                not math.isfinite(self.brake_ramp_time) or self.brake_ramp_time<=0):
            raise ValueError('Invalid brake_motor_ramp_35_to_zero_s')
        self.steering_return_enabled=cfg.get('brake_steering_return_enabled',False)
        self.steering_return_time=cfg.get('brake_steering_full_left_to_zero_s',1.)
        if type(self.steering_return_enabled) is not bool:raise ValueError('Invalid brake_steering_return_enabled')
        if self.steering_return_enabled and (type(self.steering_return_time) not in (int,float) or
                not math.isfinite(self.steering_return_time) or self.steering_return_time<=0):
            raise ValueError('Invalid brake_steering_full_left_to_zero_s')
        for name in ('brake_decel_mps2','reaction_s','stop_margin_m','front_from_lidar_m',
                     'sensor_timeout_s','max_accel_kphps','wheel_diameter_m'):
            value=cfg[name]
            if isinstance(value,bool) or not math.isfinite(value) or value<=0:
                raise ValueError('Invalid '+name)
        if not math.isfinite(cfg['steering_zero_deg']) or abs(cfg['steering_zero_deg'])>=17.01:
            raise ValueError('Invalid steering zero')
        # Constant angular rate, referenced to full left -> calibrated straight ahead.
        self.steering_return_rate_degps=((17.01-cfg['steering_zero_deg'])/self.steering_return_time
                                        if self.steering_return_enabled else 0.)
        if self.steering_return_enabled and not math.isfinite(self.steering_return_rate_degps):
            raise ValueError('Invalid brake_steering_full_left_to_zero_s')
        # Operator-started straight creep before the course lines are first confirmed.
        for name,upper,allow_zero in (('blind_start_kph',10,True),('blind_start_timeout_s',10,False)):
            value=speeds[name]
            if isinstance(value,bool) or not math.isfinite(value) or not (0<=value if allow_zero else 0<value) or value>upper:
                raise ValueError('Invalid '+name)
        if type(speeds['line_confirm_frames']) is not int or not 1<=speeds['line_confirm_frames']<=10:
            raise ValueError('Invalid line_confirm_frames')
        self.reached=False;self.moving=False;self.latched=None
        self.angle=0.;self.target=0.;self.distance=None;self.previous_time=None;self.last_frame=None
        self.brake_threshold=None
        self.brake_ramp_started=None;self.brake_ramp_initial=0.;self.brake_ramp_cancel_reason=None
        self.steering_return_started=None;self.steering_return_initial=0.;self.steering_return_cancel_reason=None
        # hold: wait for Enter (brake) or GNSS motion (creep); blind/drive: existing logic.
        self.phase='hold';self.lines=0;self.line_frame=None
        self.path_missing_frames=0;self.path_frame=None
        self.blind_started=None;self.blind_distance=0.
        self.startup_commanded=False;self.startup_motion_count=0;self.startup_sample_time=None

    def lines_confirmed(self):
        return self.lines>=self.speeds['line_confirm_frames']

    def begin(self, now, blind=False):
        if self.latched or self.phase!='hold':return False
        self.phase='blind' if blind else 'drive'
        if blind:self.blind_started=now;self.blind_distance=0.
        # Real start follows confirmed motion, without another line-confirmation wait.
        elif not self.test_mode:self.moving=True
        return True

    def stop(self, reason):
        if self.latched is None:self.latched=reason
        # Preserve the first stop reason, but a later protective/operator stop
        # must cancel a normal braking ramp permanently.
        if self.brake_motor_ramping:self.brake_ramp_cancel_reason=reason
        if self.brake_steering_returning:self.steering_return_cancel_reason=reason
        self.target=0.

    @property
    def brake_motor_ramping(self):
        return self.brake_ramp_started is not None and self.target>0 and self.brake_ramp_cancel_reason is None

    @property
    def brake_steering_returning(self):
        return (self.steering_return_started is not None and abs(self.angle)>1e-12
                and self.steering_return_cancel_reason is None)

    def update_brake_steering(self, reason, now):
        if (reason=='stop_row_braking' and self.steering_return_enabled and now is not None
                and self.steering_return_cancel_reason is None):
            if self.steering_return_started is None:
                # Anchor to the last transmitted angle, including output saturation.
                zero=self.cfg['steering_zero_deg']
                board_deg=max(-17.01,min(17.01,math.degrees(self.angle)+zero))
                self.steering_return_initial=math.radians(board_deg-zero)
                self.steering_return_started=now
            elapsed=max(0.,now-self.steering_return_started)
            remaining=abs(self.steering_return_initial)-math.radians(self.steering_return_rate_degps)*elapsed
            self.angle=math.copysign(remaining,self.steering_return_initial) if remaining>1e-12 else 0.
        elif self.brake_steering_returning:
            self.steering_return_cancel_reason=reason

    def check_stop_row(self, observation, speed, now):
        if observation['frame']!=self.last_frame:
            self.last_frame=observation['frame']
            if observation.get('stop_state')=='confirmed':
                measured=max(0.,observation['stop_distance_m']-speed*(now-observation['time']))
                self.distance=measured if self.distance is None else min(self.distance,measured)
        threshold=(self.cfg['front_from_lidar_m']+self.cfg['stop_margin_m']+
                   speed*self.cfg['reaction_s']+speed*speed/(2*self.cfg['brake_decel_mps2']))
        self.brake_threshold=threshold
        if self.distance is not None and self.distance<=threshold:
            self.latched='stop_row_braking'
            return self.result(True,self.latched,threshold,ramp_now=now)
        return None

    def step(self, observation, speed, speed_time, now, dt, fault=None):
        dt=max(0.,min(dt,.1))
        valid_speed=speed is not None and math.isfinite(speed) and speed>=0 and speed_time is not None and 0<=now-speed_time<=self.cfg['sensor_timeout_s']
        if self.previous_time is not None and now<self.previous_time:fault='clock_reversed'
        elapsed=0 if self.previous_time is None else max(0.,now-self.previous_time)
        self.previous_time=now
        if self.distance is not None and valid_speed:self.distance=max(0.,self.distance-speed*elapsed)
        fresh=observation is not None and 0<=now-observation['time']<=self.cfg['sensor_timeout_s']
        # Count distinct consecutive scans with a usable center line; any gap resets.
        if not fresh:self.lines=0
        elif observation['frame']!=self.line_frame:
            self.line_frame=observation['frame']
            usable=observation.get('path') is not None and observation.get('ground')=='near_verified'
            self.lines=self.lines+1 if usable else 0
        if self.phase=='hold':
            if fault:self.stop(fault)
            if self.latched or self.test_mode:return self.result(True,self.latched or 'operator_wait')
            if not valid_speed:
                self.startup_motion_count=0
            # Sensor readiness is checked by the operator. Available stop-row data
            # still takes precedence, but missing data does not gate the creep command.
            if fresh and valid_speed:
                braking=self.check_stop_row(observation,speed,now)
                if braking is not None:return braking
            # Count new GNSS measurements only, after the first creep command.
            if valid_speed and self.startup_commanded and speed_time!=self.startup_sample_time:
                threshold=min(.5,self.startup_speed_kph/3.6/2)
                self.startup_motion_count=self.startup_motion_count+1 if speed>threshold else 0
            self.startup_sample_time=speed_time;self.startup_commanded=True
            self.angle=0.;self.target=self.startup_speed_kph/3.6
            return self.result(False,'startup_wait_motion')
        if self.phase=='blind' and not self.latched:
            if fault or not (fresh and valid_speed):
                self.stop(fault or 'blind_start_sensor_lost')
                return self.result(True,self.latched)
            self.blind_distance+=speed*elapsed
            if self.lines_confirmed():self.phase='drive'
            elif now-self.blind_started>self.speeds['blind_start_timeout_s']:
                self.stop('blind_start_timeout')
                return self.result(True,self.latched)
            else:
                self.target=min(self.speeds['blind_start_kph']/3.6,self.target+self.cfg['max_accel_kphps']/3.6*dt)
                self.angle=0.;self.moving=True
                return self.result(False,'blind_start')
        path_available=fresh and observation.get('path') is not None
        # A missing corridor leaves ground unchecked; an explicitly unreliable
        # ground estimate or stale sensors still requires an immediate stop.
        ground_ok=fresh and (observation.get('ground')=='near_verified' or
                            (not path_available and observation.get('ground')=='unchecked'))
        healthy=(fresh and ground_ok
                 and valid_speed and (self.moving or self.lines_confirmed()))
        if fault or not healthy:
            if self.moving or fault or self.latched:self.stop(fault or 'sensor_or_path_lost')
            reason=self.latched or 'waiting_for_sensors'
            return self.result(True,reason)
        # Count lidar observations, not the faster control timer. A usable path
        # breaks the consecutive run, including while the stop remains latched.
        if self.moving and observation['frame']!=self.path_frame:
            self.path_frame=observation['frame']
            self.path_missing_frames=0 if path_available else self.path_missing_frames+1
        if self.path_missing_frames>=self.path_loss_stop_frames:
            self.stop('sensor_or_path_lost')
            return self.result(True,self.latched)
        if self.latched:return self.result(True,self.latched,ramp_now=now)
        # Braking always wins, including before the speed milestone.
        braking=self.check_stop_row(observation,speed,now)
        if braking is not None:return braking
        threshold=self.brake_threshold
        if not path_available:
            # Keep the last steering/speed command without accelerating. A
            # remembered stop row is still checked above throughout this grace.
            return self.result(False,'path_loss_grace',threshold)
        angle=self.core.steering(observation['path'],speed)
        if angle is None:
            if self.moving:self.latched='invalid_pursuit'
            return self.result(True,self.latched or 'invalid_pursuit',threshold)
        if speed*3.6>=self.speeds['max_speed']:self.reached=True
        goal=self.speeds['high_speed' if self.speeds['use_high_speed'] else 'low_speed'] if self.reached else self.speeds['max_speed']
        self.target=min(goal/3.6,self.target+self.cfg['max_accel_kphps']/3.6*dt)
        self.angle=angle;self.moving=True
        return self.result(False,'maintain' if self.reached else 'accelerate',threshold)

    def result(self, brake, reason, threshold=None, ramp_now=None):
        if brake:
            self.update_brake_steering(reason,ramp_now)
            if (reason=='stop_row_braking' and self.brake_ramp_enabled and ramp_now is not None
                    and self.brake_ramp_cancel_reason is None):
                if self.brake_ramp_started is None:
                    self.brake_ramp_started=ramp_now;self.brake_ramp_initial=self.target
                # Anchor to the last command at brake onset, never to GNSS speed.
                # Use monotonic elapsed time rather than the capped acceleration dt.
                elapsed=max(0.,ramp_now-self.brake_ramp_started)
                remaining=self.brake_ramp_initial-(35./3.6)*elapsed/self.brake_ramp_time
                self.target=min(self.target,max(0.,remaining)) if remaining>1e-12 else 0.
            else:
                if self.brake_motor_ramping:self.brake_ramp_cancel_reason=reason
                self.target=0.
        ramping=brake and self.brake_motor_ramping
        # Keep the shared C++ brake->zero contract. Only this normal-stop path
        # converts the decreasing speed separately and immediately sets brake=1.
        raw=self.core.raw(self.angle,self.target,brake and not ramping,
                          self.cfg['steering_zero_deg'],self.cfg['wheel_diameter_m'])
        if ramping:raw[2]=1.
        ramp_state=('idle' if self.brake_ramp_started is None else
                    'cancelled' if self.brake_ramp_cancel_reason else 'active' if ramping else 'completed')
        steering_state=('idle' if self.steering_return_started is None else
                        'cancelled' if self.steering_return_cancel_reason else
                        'active' if self.brake_steering_returning else 'completed')
        return dict(raw=raw,reason=reason,brake=brake,target_kph=self.target*3.6,phase=self.phase,
                    path_missing_frames=self.path_missing_frames,path_loss_stop_frames=self.path_loss_stop_frames,
                    reached_max_speed=self.reached,stop_distance_m=self.distance,
                    brake_distance_m=self.brake_threshold if threshold is None else threshold,
                    brake_motor_ramp=dict(state=ramp_state,start_kph=self.brake_ramp_initial*3.6,
                        elapsed_s=(max(0.,self.previous_time-self.brake_ramp_started)
                                   if self.brake_ramp_started is not None and self.previous_time is not None else 0.),
                        reference_time_s=self.brake_ramp_time if self.brake_ramp_enabled else None,
                        cancel_reason=self.brake_ramp_cancel_reason),
                    brake_steering_return=dict(state=steering_state,start_deg=math.degrees(self.steering_return_initial),
                        command_deg=math.degrees(self.angle),zero_deg=self.cfg['steering_zero_deg'],
                        elapsed_s=(max(0.,self.previous_time-self.steering_return_started)
                                   if self.steering_return_started is not None and self.previous_time is not None else 0.),
                        full_left_to_zero_s=self.steering_return_time if self.steering_return_enabled else None,
                        rate_degps=self.steering_return_rate_degps,cancel_reason=self.steering_return_cancel_reason))
