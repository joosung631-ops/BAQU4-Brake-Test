#!/usr/bin/env python3
"""Host-side, noninteractive PNG rendering after a confirmed stop. No ROS imports."""
import argparse
from bisect import bisect_left
import csv
import json
import math
from pathlib import Path
import shutil
import time


def analyse(job):
    odom=job['odometry']
    valid=[s for s in odom if s['position_m'] is not None]
    origin=valid[0]['position_m'] if valid else None
    frame=valid[0]['frame'] if valid else None
    valid=[s for s in valid if s['frame']==frame]
    direction=None
    if origin is not None:
        # Infer the initial direction from measured movement, not stopped GNSS yaw.
        for s in valid:
            dx,dy=(s['position_m'][i]-origin[i] for i in (0,1))
            length=math.hypot(dx,dy)
            if length>=1.:
                direction=[dx/length,dy/length];break
    warnings=[]
    if direction is None:
        if valid:
            far=max(valid,key=lambda s:math.dist(s['position_m'],origin))
            dx,dy=(far['position_m'][i]-origin[i] for i in (0,1))
            length=math.hypot(dx,dy)
            direction=[dx/length,dy/length] if length>=.05 else [1.,0.]
        warnings.append('Less than 1 m of GNSS displacement; initial direction is uncertain.')
    if origin is None:warnings.append('No valid GNSS positions; displacement plots are unavailable.')
    if any(s['position_m'] is not None and s['frame']!=frame for s in odom):
        warnings.append('GNSS frame changed; positions from other frames are omitted.')
    def project(sample):
        if sample['position_m'] is None or origin is None or sample['frame']!=frame:return None
        return sum((sample['position_m'][i]-origin[i])*direction[i] for i in (0,1))
    times=[s['time'] for s in odom]
    positions=[project(s) for s in odom]
    timeout=job['config']['sensor_timeout_s']
    def at(t):
        if not times:return None
        i=bisect_left(times,t)
        if i<len(times) and times[i]==t:return positions[i]
        if i==0:return positions[0] if times[0]-t<=timeout else None
        if i==len(times):return positions[-1] if t-times[-1]<=timeout else None
        if times[i]-times[i-1]>timeout or positions[i-1] is None or positions[i] is None:return None
        ratio=(t-times[i-1])/(times[i]-times[i-1])
        return positions[i-1]*(1-ratio)+positions[i]*ratio
    speed=[dict(time=s['time'],x=positions[i],kph=s['speed_mps']*3.6 if s['speed_mps'] is not None else None)
           for i,s in enumerate(odom)]
    commands=[dict(s,x=at(s['time'])) for s in job['commands']]
    yaw=math.radians(job['config'].get('lidar_yaw_offset_deg',0.))
    cones=[];rows=[]
    for scan in job['scans']:
        x=at(scan['time'])
        for center in scan['cones_lidar_m']:
            # os_lidar -X points forward; distance stays relative to the LiDAR.
            forward=-center[0]*math.cos(yaw)+center[1]*math.sin(yaw)
            cones.append(dict(time=scan['time'],x=x,distance_m=forward,lidar_xyz_m=center))
        if scan['row_distance_m'] is not None:
            rows.append(dict(time=scan['time'],x=x,distance_m=scan['row_distance_m'],state=scan['row_state']))
    return dict(speed=speed,commands=commands,cones=cones,rows=rows,origin_m=origin,
                direction=direction,brake_x=at(job['brake_time']) if job['brake_time'] is not None else None,
                stopped_x=at(job['stopped_since']),warnings=warnings)


def render(job_path, output_root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    job=json.loads(Path(job_path).read_text())
    if job.get('stop_confirmed') is not True:raise ValueError('A confirmed stop is required')
    data=analyse(job)
    output_root=Path(output_root);output_root.mkdir(parents=True,exist_ok=True)
    name=job['output_name']
    if len(name)!=13 or name[6]!='_' or not (name[:6]+name[7:]).isdigit():
        raise ValueError('Expected YYMMDD_HHMMSS output name')
    for suffix in range(1000):
        destination=output_root/(name if suffix==0 else f'{name}_{suffix:02d}')
        try:destination.mkdir();break
        except FileExistsError:continue
    else:raise FileExistsError('No unused output directory')
    shutil.copy2(job_path,destination/'report.json')
    summary={k:job[k] for k in ('completed_at','max_speed_kph','reason','stop_confirmed','started',
                               'brake_time','stopped_since','confirmed_at','config','speeds')}
    summary.update(origin_m=data['origin_m'],initial_direction=data['direction'],
        displacement_definition='GNSS position minus start position, projected onto initial measured direction (m)',
        cone_definition='Measured cone forward distance relative to LiDAR (m); stop row uses course direction',
        motor_definition='/cmd[1] normalized raw; trans UDP motor RPM = -raw * 891.387',
        stop_definition='Fresh valid GNSS speed <= 0.1 m/s for >= 0.5 s and motor command zero',
        published_cmd=any(s['published'] for s in job['commands']),warnings=data['warnings'])
    (destination/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with (destination/'samples.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['kind','time_s','displacement_m','speed_kph','motor_raw','motor_udp_rpm','brake_raw','published'])
        for s in data['speed']:writer.writerow(['gnss',s['time']-job['started'],s['x'],s['kph'],'','','',''])
        for s in data['commands']:
            writer.writerow(['command',s['time']-job['started'],s['x'],'',s['raw'][1],-s['raw'][1]*891.387,s['raw'][2],s['published']])
    with (destination/'cones.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['kind','time_s','displacement_m','lidar_forward_m','state'])
        for s in data['cones']:writer.writerow(['cone',s['time']-job['started'],s['x'],s['distance_m'],'detected'])
        for s in data['rows']:writer.writerow(['stop_row',s['time']-job['started'],s['x'],s['distance_m'],s['state']])
    fonts={f.name for f in font_manager.fontManager.ttflist}
    korean=next((f for f in ('NanumGothic','Noto Sans CJK JP','Noto Sans CJK KR') if f in fonts),None)
    def label(ko,en):return ko if korean else en
    style={'font.size':11,'axes.unicode_minus':False}
    if korean:style['font.family']=korean
    def values(items,key):return [s[key] if s[key] is not None else math.nan for s in items]
    with plt.rc_context(style):
        fig,axes=plt.subplots(3,1,figsize=(14,12),sharex=True,constrained_layout=True)
        fig.suptitle(label('제동 테스트 주행 결과','Brake test run')+' | '+job['completed_at'][:19].replace('T',' '),fontsize=18)
        ax=axes[0]
        ax.plot(values(data['speed'],'x'),values(data['speed'],'kph'),color='#1768ac',lw=2,label=label('GNSS 실측 속도','Measured GNSS speed'))
        ax.plot(values(data['commands'],'x'),[s['target_kph'] for s in data['commands']],color='#78909c',ls='--',lw=1.2,
                label=label('모터 목표 속도','Motor target speed'))
        ax.axhline(30,color='#b0bec5',ls=':',lw=1)
        peak=max((s for s in data['speed'] if s['kph'] is not None),key=lambda s:s['kph'],default=None)
        if peak is not None and peak['x'] is not None:
            ax.scatter([peak['x']],[peak['kph']],color='#1768ac',s=40,zorder=5)
        ax.set_title(label('1. 속도','1. Speed')+f" | MAX {job['max_speed_kph']:.2f} km/h",loc='left',fontweight='bold')
        ax.set_ylabel(label('속도 (km/h)','Speed (km/h)'));ax.legend(loc='upper left')
        ax=axes[1]
        ax.scatter(values(data['cones'],'x'),values(data['cones'],'distance_m'),s=9,color='#78909c',alpha=.35,
                   label=label('개별 콘 전방 거리','Detected cone forward distance'))
        for state,color,text in (('candidate','#c79320',label('정지열 후보','Candidate stop row')),
                                 ('confirmed','#df5a32',label('확인된 정지열','Confirmed stop row'))):
            subset=[s for s in data['rows'] if s['state']==state]
            if subset:ax.scatter(values(subset,'x'),values(subset,'distance_m'),s=22,color=color,label=text)
        if not data['cones'] and not data['rows']:
            ax.text(.5,.5,label('실측 콘/정지열 데이터 없음','No measured cone / stop-row data'),ha='center',transform=ax.transAxes)
        ax.set_title(label('2. 라이다 실측 콘 위치 (센서 기준 상대 거리)','2. Measured cone position relative to LiDAR'),loc='left',fontweight='bold')
        ax.set_ylabel(label('콘까지 전방 거리 (m)','Forward distance to cone (m)'));ax.legend(loc='upper right')
        ax=axes[2];commands=data['commands']
        ax.step(values(commands,'x'),[s['raw'][1] for s in commands],where='post',color='#14866d',lw=2,label='Motor /cmd[1]')
        ax.step(values(commands,'x'),[s['raw'][2] for s in commands],where='post',color='#c3423f',lw=1.8,label='Brake /cmd[2]')
        ax.set_title(label('3. 위치별 모터·브레이크 명령','3. Motor and brake commands by position'),loc='left',fontweight='bold')
        ax.set_ylabel(label('명령 raw (브레이크: 0/1)','Command raw (brake: 0/1)'));ax.set_ylim(-.05,1.12)
        ax.set_xlabel(label('출발 위치·초기 진행방향 기준 전방 변위 (m)','Forward displacement from start along initial direction (m)'))
        ax.legend(loc='upper left')
        for ax in axes:
            ax.grid(alpha=.2)
            if data['brake_x'] is not None:
                ax.axvline(data['brake_x'],color='#c3423f',ls='--',lw=1,alpha=.65)
            if data['stopped_x'] is not None:
                ax.axvline(data['stopped_x'],color='#263238',ls=':',lw=1,alpha=.65)
        subtitle=label('빨간 점선: 제동 명령 시작 | 검정 점선: 정지 구간 시작 | 동일 위치의 명령은 겹쳐 보일 수 있음',
                       'Red dashed: brake command | Black dotted: stop interval | Commands at the same position can overlap')
        if not summary['published_cmd']:subtitle+=' | '+label('모의 실행: /cmd 미발행','DRY RUN: /cmd not published')
        if data['warnings']:subtitle+=' | '+label('변위 데이터 제한: summary.json 참고','Limited displacement data: see summary.json')
        axes[2].text(.5,-.26,subtitle,ha='center',va='top',transform=axes[2].transAxes,fontsize=9)
        path=destination/'run_summary.png'
        fig.savefig(path,dpi=160,facecolor='white');plt.close(fig)
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path)
    parser.add_argument('--output-root',type=Path)
    parser.add_argument('--done-file',type=Path)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.check:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot
        return
    if args.job is None or args.output_root is None:parser.error('--job and --output-root required')
    while not args.job.exists():
        if args.done_file is None:raise FileNotFoundError(args.job)
        if args.done_file.exists():
            print('[stop_test] 완전 정지 기록이 없어 주행 그래프를 생성하지 않았습니다.',flush=True);return
        time.sleep(.2)
    path=render(args.job,args.output_root)
    print('[stop_test] 주행 그래프 저장: '+str(path),flush=True)


if __name__=='__main__':main()
