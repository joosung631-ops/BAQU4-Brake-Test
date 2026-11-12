"""Latest-only, display-only driver telemetry; independent of ROS domain."""
import math
import time


class PredictionStore:
    def __init__(self):
        self.value=None;self.received=0.

    def put(self, value):
        if not isinstance(value,dict):raise ValueError('Expected prediction object')
        session=value.get('session');seq=value.get('seq')
        if not isinstance(session,str) or not 8<=len(session)<=64 or type(seq) is not int or not 0<=seq<2**53:
            raise ValueError('Invalid prediction identity')
        out=dict(session=session,seq=seq)
        for name,low,high in [('angle_deg',-35,35),('wheelbase_m',.5,4),('width_m',.5,3),
                              ('lidar_x_m',-3,3),('lidar_y_m',-2,2),('yaw_deg',-180,180),('cloud_stamp_s',0,1e13)]:
            v=value.get(name)
            if type(v) not in (float,int) or not math.isfinite(v) or not low<=v<=high:
                raise ValueError('Invalid '+name)
            out[name]=v
        speed=value.get('speed_mps')
        if speed is not None and (type(speed) not in (float,int) or not math.isfinite(speed) or not 0<=speed<=50):
            raise ValueError('Invalid speed')
        out['speed_mps']=speed
        for name in ('brake','publish_cmd','sensors_fresh'):
            if type(value.get(name)) is not bool:raise ValueError('Invalid '+name)
            out[name]=value[name]
        if 'drive' in value:
            drive=value['drive']
            if not isinstance(drive,dict):raise ValueError('Invalid drive status')
            reason=drive.get('reason')
            if not isinstance(reason,str) or not 1<=len(reason)<=64 or not all(c.isascii() and (c.isalnum() or c=='_') for c in reason):
                raise ValueError('Invalid drive reason')
            clean={'reason':reason}
            for name in ('command_kph','goal_kph','max_speed_kph'):
                v=drive.get(name)
                if type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=50:raise ValueError('Invalid '+name)
                clean[name]=v
            for name in ('reached_max_speed','accelerating'):
                if type(drive.get(name)) is not bool:raise ValueError('Invalid '+name)
                clean[name]=drive[name]
            # Optional for drivers launched before stop-distance telemetry was added.
            if 'stop_state' in drive:
                if drive['stop_state'] not in ('none','candidate','confirmed','unavailable'):
                    raise ValueError('Invalid stop state')
                clean['stop_state']=drive['stop_state']
            for name in ('stop_distance_m','brake_distance_m'):
                if name not in drive:continue
                v=drive[name]
                if v is not None and (type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=1000):
                    raise ValueError('Invalid '+name)
                clean[name]=v
            out['drive']=clean
        if self.value and session==self.value['session'] and seq<=self.value['seq']:
            raise ValueError('Old prediction sequence')
        self.value=out;self.received=time.monotonic()

    def snapshot(self):
        return dict(self.value) if self.value and time.monotonic()-self.received<.7 else None
