"""Observation only: collect a run and confirm stopping using fresh GNSS samples."""
from datetime import datetime
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo


class RunTelemetry:
    def __init__(self, timeout_s):
        self.timeout_s=timeout_s
        self.started=None;self.latest=None;self.brake_time=None
        self.odometry=[];self.commands=[];self.scans=[]
        self.low_since=None;self.low_count=0;self.last_low=None
        self.finished=False

    def start(self, now):
        if self.started is not None:return
        self.started=now
        if self.latest is not None and 0<=now-self.latest['time']<=self.timeout_s:
            self.odometry.append(dict(self.latest))

    def odom(self, now, stamp_ns, speed, position, frame):
        sample=dict(time=now,stamp_ns=stamp_ns,speed_mps=speed,position_m=position,frame=frame)
        self.latest=sample
        if self.started is None or self.finished:return
        self.odometry.append(sample)
        if self.brake_time is None:return
        if speed is None or not math.isfinite(speed) or abs(speed)>.1:
            self.low_since=None;self.last_low=None;self.low_count=0
        else:
            if self.last_low is None or not 0<now-self.last_low<=self.timeout_s:
                self.low_since=now;self.low_count=0
            self.last_low=now;self.low_count+=1

    def command(self, now, result, published):
        if self.started is None or self.finished:return
        self.commands.append(dict(time=now,raw=list(result['raw']),published=published,
                                  reason=result['reason'],target_kph=result['target_kph']))
        if result['brake'] and self.brake_time is None:self.brake_time=now

    def scan(self, observation):
        if self.started is None or self.finished or observation['time']<self.started:return
        self.scans.append(dict(time=observation['time'],frame=observation['frame'],
            cones_lidar_m=observation.get('cones_lidar_m',[]),
            row_state=observation.get('stop_state','none'),
            row_distance_m=(observation.get('stop_distance_m')
                            if observation.get('stop_state') in ('candidate','confirmed') else None)))

    def stopped(self, now):
        return (self.low_since is not None and self.low_count>=3 and
                now-self.low_since>=.5 and self.last_low is not None and
                0<=now-self.last_low<=self.timeout_s and self.commands and
                abs(self.commands[-1]['raw'][1])<1e-9)

    def snapshot(self, now, cfg, speeds, reason):
        self.finished=True
        speeds_mps=[v['speed_mps'] for v in self.odometry if v['speed_mps'] is not None]
        wall=datetime.now(ZoneInfo('Asia/Seoul'))
        return dict(schema=1,started=self.started,brake_time=self.brake_time,
            stopped_since=self.low_since,confirmed_at=now,stop_confirmed=True,
            completed_at=wall.isoformat(),output_name=wall.strftime('%y%m%d_%H%M%S'),
            max_speed_kph=max(speeds_mps)*3.6 if speeds_mps else None,
            reason=reason,config=dict(cfg),speeds=dict(speeds),
            odometry=list(self.odometry),commands=list(self.commands),scans=list(self.scans))


def write_job(path, snapshot):
    """Atomic handoff to the independent host renderer; never render in ROS callbacks."""
    path=Path(path)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot,ensure_ascii=False,allow_nan=False)+'\n')
    temporary.replace(path)
