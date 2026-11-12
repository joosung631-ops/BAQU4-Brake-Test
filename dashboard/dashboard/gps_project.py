"""One revisioned project file containing source GPS and all workflow stages."""
import asyncio
import copy
import hashlib
from datetime import datetime, timezone
import json
import math
import os
import re
from zoneinfo import ZoneInfo
from pathlib import Path
import tempfile
import uuid
from collections import OrderedDict
from aiohttp import web
from .camera_projection_config import projection_config
from .gps_final_points import final_point_source, final_point_result
from .gps_sections import section_source, section_result
from .gps_export import final_map, user_suffix
from .gps_lane import road_config, lane_source, lane_settings, validate_lane_width, lane_edges, vehicle_display_config
from .gps_path import path_source, path_settings, vehicle_config, generate_path, PATH_METHOD, single_path_result
from .gps_ordering import ordering_source, automatic_order, order_result
from .gps_fusion import source_points, fused_points, automatic_groups, fusion_curves
from .gps_review import identify, build_review, digest, curve_segment
from .gps_workflow import directory as legacy_directory, valid_name, load_snapshot, stage_one, merge_tracks
from .gps_additions import addition_result
from .gps_map_merge import effective_raw, placement_result, upgrade_reference_background


def directory():
    return legacy_directory().parent/'maps'


def load(name):
    path=directory()/valid_name(name)
    if not path.is_file(): raise web.HTTPNotFound(text='맵 설정 파일이 없습니다.')
    data=json.loads(path.read_text())
    if data.get('format')!='gps-map-project': raise web.HTTPBadRequest(text='맵 설정 파일이 아닙니다.')
    if data.get('version', 1) < 2:
        for stages in [data['stages'], *(entry.get('stages', {}) for entry in data.get('history', []))]:
            if '10' in stages: stages['11'] = stages.pop('10')
            if '9' in stages: stages['10'] = stages.pop('9')
        data['version'] = 2
    if data.get('version', 1) < 3:
        for stages in [data['stages'], *(entry.get('stages', {}) for entry in data.get('history', []))]:
            for number in range(11, 3, -1):
                if str(number) in stages:
                    stages[str(number+1)] = stages.pop(str(number))
        data['version'] = 3
    for stages in [data['stages'], *(entry.get('stages',{}) for entry in data.get('history',[]))]:
        if '8' in stages and len(stages['8'].get('segments',[]))==1:
            stages['8']=single_path_result(stages['8'])
    upgrade_reference_background(data)
    return data


def response(name,data):
    return {'filename':name,'path':str(directory()/name),
            'workspace_path':'main/decision/script/map_generator/test/review/maps/'+name,'project':data}


def write(name,data,create=False):
    path=directory()/valid_name(name);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,encoding='utf-8',delete=False) as f:
        temporary=Path(f.name)
        try:
            json.dump(data,f,ensure_ascii=False,allow_nan=False,indent=2);f.flush();os.fsync(f.fileno())
        except BaseException: temporary.unlink(missing_ok=True);raise
    try:
        temporary.chmod(0o664)
        if create:
            try: os.link(temporary,path)
            except FileExistsError: raise web.HTTPConflict(text='이미 있는 파일 이름입니다. 다른 이름을 입력하세요.')
        else: temporary.replace(path)
    finally: temporary.unlink(missing_ok=True)
    return response(name,data)


def display_stage(project, stage):
    """Keep persisted stage keys stable while numbering the optional MAP step."""
    if stage == 'map-merge' or stage == 2.5: return 3
    stage = 11 if stage == 10.5 else stage + int(stage >= 11)
    return stage + int(stage >= 3 and project['stages'].get('2', {}).get('map_merge', False) is True)


def last_stage(project):
    return max(max(map(float,project['stages'])), 2.5 if project.get('map_merge_result') else 1)


def refresh_write(name,project,stage=None):
    suffix=user_suffix(name)
    stage=int(display_stage(project, stage if stage is not None else last_stage(project)))
    now=datetime.now(ZoneInfo('Asia/Seoul'))
    new_name=f"{stage}단계_{now:%Y-%m-%d_%H%M%S}_{suffix}.json"
    if new_name==name or (directory()/new_name).exists():
        new_name=f"{stage}단계_{now:%Y-%m-%d_%H%M%S%f}_{suffix}.json"
    result=write(new_name,project,True)
    try:(directory()/name).unlink()
    except OSError:
        (directory()/new_name).unlink(missing_ok=True)
        raise
    return result


def review(raw,specs=None):
    tracks,dataset=identify(raw)
    if specs is not None and (not isinstance(specs,list) or len(specs)!=len(tracks) or any(not isinstance(s,dict) for s in specs) or {s.get('id') for s in specs}!={t['id'] for t in tracks}):
        raise web.HTTPBadRequest(text='선택 기록과 편집 기록이 일치하지 않습니다.')
    known={s['id']:s for s in specs or []};result=[]
    for t in tracks:
        s=known.get(t['id'],{})
        try: result.append(build_review(t,raw['origin'],s.get('manual_excluded_seq',s.get('excluded_seq',[])),s.get('smoothing_m',.5),s.get('complete',False),s.get('start_seq'),s.get('end_seq')))
        except ValueError as e: raise web.HTTPBadRequest(text=str(e))
    return {'dataset_id':dataset,'tracks':result,'origin':raw['origin']}


def retained(project):
    stages=project['stages']
    if '3' not in stages: raise web.HTTPConflict(text='먼저 3단계 GPS 노이즈 제거 결과를 저장하세요.')
    raw=effective_raw(project);tracks,dataset=identify(raw)
    return stage_one({**raw,'tracks':tracks},dataset,stages['3']['tracks'])


def augmented(project):
    source = retained(project)
    if '4' in project['stages']:
        source['tracks'] = project['stages']['4']['tracks']
    return source


def augmentation_digest(project):
    return digest(project['stages'].get('4', project['stages'].get('3')))


def merge_curves(source,specs):
    tracks=merge_tracks(source,specs);lat,lon=source['origin'];result=[]
    for t in tracks:
        segments=[];current=[];previous=None
        for p in t['points']:
            if previous is not None and p['segment']!=previous:
                segments.append(curve_segment(current,.5));current=[]
            current.append({**p,'e':math.radians(p['lon']-lon)*6378137*math.cos(math.radians(lat)),
                            'n':math.radians(p['lat']-lat)*6378137})
            previous=p['segment']
        if current:segments.append(curve_segment(current,.5))
        result.append({'id':t['id'],'curve_segments':segments})
    return result


def invalidate(project,after):
    stale={k:v for k,v in project['stages'].items() if float(k)>after}
    if stale:
        project.setdefault('history',[]).append({'revision':project['revision'],'reason':f'{after}단계 입력 변경','stages':stale})
        for k in stale:del project['stages'][k]


def add_routes(app):
    lock=asyncio.Lock()
    path_lock=asyncio.Lock()
    path_previews=OrderedDict()
    root=Path(os.environ.get('DASHBOARD_GPS_MAP_DIR',Path(__file__).resolve().parents[2]/'main/decision/script/map_generator'))
    async def body(request):
        if request.headers.get('X-Dashboard-Control')!='1' or request.content_type!='application/json':raise web.HTTPForbidden()
        try:data=await request.json()
        except ValueError:raise web.HTTPBadRequest(text='잘못된 요청입니다.')
        if not isinstance(data,dict):raise web.HTTPBadRequest()
        return data
    async def listing(request):
        entries=[]
        for p in sorted(directory().glob('*.json'),reverse=True):
            try:
                d=await asyncio.to_thread(load,p.name);entries.append({'filename':p.name,'kind':'project','revision':d['revision'],'last_stage':last_stage(d),'map_merge':d['stages'].get('2',{}).get('map_merge',False)})
            except (ValueError,web.HTTPException):continue
        for p in sorted(legacy_directory().glob('*.json'),reverse=True):
            try:
                d=await asyncio.to_thread(load_snapshot,p.name);entries.append({'filename':p.name,'kind':'legacy','stage':d['stage']})
            except (ValueError,web.HTTPException):continue
        if (legacy_directory().parent/'review.json').is_file():
            entries.append({'filename':'review.json','kind':'review'})
        return web.json_response({'files':entries},headers={'Cache-Control':'no-store'})
    async def read(request):
        name=request.query.get('filename','');return web.json_response(response(name,await asyncio.to_thread(load,name)),headers={'Cache-Control':'no-store'})
    def create(data):
        name=valid_name(data.get('filename'));now=datetime.now(timezone.utc).isoformat()
        if data.get('source'):
            if data.get('kind')=='review':
                saved=json.loads((legacy_directory().parent/'review.json').read_text())
                raw=json.loads((root/'test/raw.json').read_text());tracks,_=identify(raw)
                if not any(t['id'] in saved.get('tracks',{}) for t in tracks):
                    raise web.HTTPConflict(text='현재 원본 GPS와 이전 검토 기록이 일치하지 않습니다. 당시 로스백을 먼저 불러오세요.')
                specs=[{**saved.get('tracks',{}).get(t['id'],{}),'id':t['id']} for t in tracks]
                rv=review(raw,specs)
                project={'format':'gps-map-project','version':3,'stages':{'1':{'created_at':now},
                    '2':{'raw':raw,'dataset_id':rv['dataset_id'],'bags':raw.get('selected_bags',[]),'display':{'linear':True,'smooth':True}},'3':rv},
                    'import_note':'기존 review.json에서 현재 원본 GPS와 일치하는 기록의 제외·범위를 가져왔습니다.'}
            elif data.get('kind')=='legacy':
                old=load_snapshot(data['source']);src=old if old['stage']==1 else load_snapshot(old['source_file'])
                raw={'format':'gps-test-raw','version':1,'origin':src['origin'],'tracks':[]}
                for t in src['tracks']:
                    ps=[];last=None
                    for p in t['points']:
                        segment=p.get('segment',0);ps.append({**p,'break_before':last is not None and segment!=last});last=segment
                    raw['tracks'].append({'name':t['name'],'points':ps})
                rv=review(raw);stages={'1':{'created_at':now},'2':{'raw':raw,'dataset_id':rv['dataset_id'],'bags':[], 'display':{'linear':True,'smooth':True}},'3':rv}
                project={'format':'gps-map-project','version':3,'stages':stages,'import_note':'이전 단계 파일의 남은 점을 가져왔습니다. 이전에 제외한 원본 점은 포함되어 있지 않습니다.'}
                if old['stage']==2:
                    specs=[{'id':new['id'],'groups':t['groups']} for new,t in zip(rv['tracks'],old['tracks'])]
                    stages['5']={'tracks':merge_tracks(retained(project),specs)}
            else:project=copy.deepcopy(load(data['source']))
            project['copied_from']=data['source']
        else:project={'format':'gps-map-project','version':3,'stages':{'1':{'created_at':now}}}
        project.update(revision=1,saved_at=now)
        return write(name,project,True)
    async def create_route(request):
        data=await body(request)
        async with lock:result=await asyncio.to_thread(create,data)
        return web.json_response(result)
    def resume(data):
        name=valid_name(data.get('filename'));project=load(name)
        if data.get('revision')!=project['revision']:raise web.HTTPConflict(text='파일이 변경됐습니다. 목록을 새로고침하세요.')
        project['revision']+=1;project['saved_at']=datetime.now(timezone.utc).isoformat()
        return refresh_write(name,project)
    async def resume_route(request):
        data=await body(request)
        async with lock:result=await asyncio.to_thread(resume,data)
        return web.json_response(result)
    def update(data):
        name=data.get('filename');project=load(name)
        if data.get('revision')!=project['revision']:raise web.HTTPConflict(text='다른 화면에서 파일이 변경됐습니다. 현재 파일을 다시 불러오세요.')
        stage=data.get('stage');stages=project['stages']
        if data.get('retain') is True and stage in (8,9):
            if str(stage) not in stages:raise web.HTTPConflict(text='먼저 해당 단계 결과를 생성하세요.')
            if stage==9 and stages['9'].get('source_digest')!=lane_source(project)['source_digest']:
                raise web.HTTPConflict(text='직선 보간선 기준으로 9단계 차선을 다시 적용하고 저장하세요.')
            project['revision']+=1;project['saved_at']=datetime.now(timezone.utc).isoformat()
            return refresh_write(name,project,stage)
        if stage==2:
            if data.get('use_saved'):
                if '2' not in stages:raise web.HTTPConflict(text='ROS bag을 먼저 불러오세요.')
                raw=stages['2']['raw']
            else:raw=json.loads((root/'test/raw.json').read_text())
            _,dataset=identify(raw)
            if data.get('dataset_id')!=dataset:raise web.HTTPConflict(text='불러온 GPS가 변경되었습니다. 다시 불러오세요.')
            display=data.get('display',{})
            if not isinstance(display,dict) or any(type(display.get(k)) is not bool for k in ('linear','smooth')):raise web.HTTPBadRequest(text='표시 설정이 잘못되었습니다.')
            map_merge=data.get('map_merge',stages.get('2',{}).get('map_merge',False))
            if type(map_merge) is not bool:raise web.HTTPBadRequest(text='MAP 병합 설정이 잘못되었습니다.')
            bags=raw.get('selected_bags',data.get('bags',[]))
            if not isinstance(bags,list) or any(not isinstance(b,str) for b in bags):raise web.HTTPBadRequest()
            if stages.get('2',{}).get('dataset_id')!=dataset or (stages.get('2',{}).get('map_merge',False) and not map_merge):
                invalidate(project,2);project.pop('map_merge_result',None)
            stages['2']={'raw':raw,'dataset_id':dataset,'bags':bags,'display':display,'map_merge':map_merge}
        elif stage=='map-merge':
            source=stages.get('2')
            if not source or not source.get('map_merge'):raise web.HTTPConflict(text='먼저 2단계에서 MAP 병합하기를 선택하고 저장하세요.')
            if data.get('source_dataset_id')!=source['dataset_id']:raise web.HTTPConflict(text='2단계 GPS가 변경되었습니다. MAP 병합 화면을 다시 여세요.')
            result=placement_result(source,data.get('clips'))
            if digest(project.get('map_merge_result'))!=digest(result):invalidate(project,2)
            project['map_merge_result']=result
        elif stage==3:
            if '2' not in stages:raise web.HTTPConflict(text='먼저 2단계를 저장하세요.')
            if stages['2'].get('map_merge') and not effective_raw(project)['tracks']:raise web.HTTPConflict(text='먼저 MAP 병합에서 사용할 구간을 복사해 배치하세요. 기준 로스백은 배경 전용입니다.')
            if data.get('dataset_id')!=identify(effective_raw(project))[1]:raise web.HTTPConflict(text='2단계 GPS가 변경되었습니다.')
            if not isinstance(data.get('tracks'),list):raise web.HTTPBadRequest(text='편집 기록이 필요합니다.')
            rv=review(effective_raw(project),data['tracks'])
            if digest(stages.get('3'))!=digest(rv):invalidate(project,3)
            stages['3']=rv
        elif stage==4:
            if data.get('source_digest')!=digest(stages.get('3')):raise web.HTTPConflict(text='3단계 결과가 변경되었습니다. 포인트 추가 화면을 다시 여세요.')
            result=addition_result(retained(project),data.get('additions'),data['source_digest'])
            if digest(stages.get('4'))!=digest(result):invalidate(project,4)
            stages['4']=result
        elif stage==5:
            if data.get('source_digest')!=augmentation_digest(project):raise web.HTTPConflict(text='GPS 포인트가 변경되었습니다. 병합 화면을 다시 여세요.')
            merged={'tracks':merge_tracks(augmented(project),data.get('tracks'))}
            if digest(stages.get('5'))!=digest(merged):invalidate(project,5)
            stages['5']=merged
        elif stage==6:
            if data.get('source_digest')!=digest(stages.get('5')):raise web.HTTPConflict(text='5단계 결과가 변경되었습니다. 6단계를 다시 여세요.')
            points=fused_points(source_points(project),data.get('groups'))
            radius=data.get('radius_m',.5)
            if type(radius) not in (int,float) or not math.isfinite(radius) or radius<=0:raise web.HTTPBadRequest(text='올바른 병합 거리를 입력하세요.')
            fused={'groups':data['groups'],'points':points,'radius_m':radius,'source_digest':data['source_digest'],
                         'average_basis':'equal weight per stage 5 point; repeated merges preserve these weights'}
            if digest(stages.get('6'))!=digest(fused):invalidate(project,6)
            stages['6']=fused
        elif stage==7:
            if data.get('source_digest')!=digest(stages.get('6')):raise web.HTTPConflict(text='6단계 결과가 변경되었습니다. 7단계를 다시 여세요.')
            ordered={**order_result(project,data.get('reference_id'),data.get('max_distance_m'),data.get('order')),
                         'source_digest':data['source_digest']}
            if digest(stages.get('7'))!=digest(ordered):invalidate(project,7)
            stages['7']=ordered
        elif stage==8:
            if data.get('source_digest')!=digest(stages.get('7')):raise web.HTTPConflict(text='7단계 결과가 변경되었습니다. 8단계를 다시 여세요.')
            if data.get('draft') is True:
                if not isinstance(data.get('waypoints'),list):raise web.HTTPBadRequest(text='편집한 웨이포인트 목록이 필요합니다.')
                source=path_source(project,data['waypoints'])
                result={'draft':True,'valid':False,'method':PATH_METHOD,'source_digest':source['source_digest'],
                        'waypoints':source['waypoints'],'waypoints_digest':digest(source['waypoints']),
                        'settings':path_settings(data.get('settings')),'origin':source['origin']}
            else:
                cached=path_previews.get(data.get('preview_id'))
                if cached is None or cached['filename']!=name:raise web.HTTPConflict(text='경로를 다시 생성한 뒤 저장하세요.')
                result=cached['result']
                if result['source_digest']!=digest(stages.get('7')) or result['vehicle_digest']!=digest(vehicle_config()):raise web.HTTPConflict(text='GPS 또는 차량 설정이 변경되었습니다. 경로를 다시 생성하세요.')
                if 'waypoints' in data and digest(path_source(project,data['waypoints'])['waypoints'])!=result['waypoints_digest']:
                    raise web.HTTPConflict(text='웨이포인트가 변경되었습니다. 경로를 다시 생성하세요.')
                if not result['valid']:raise web.HTTPBadRequest(text='검증을 통과한 경로만 저장할 수 있습니다.')
            if digest(stages.get('8'))!=digest(result):invalidate(project,8)
            stages['8']=copy.deepcopy(result)
        elif stage==9:
            source=lane_source(project)
            if data.get('source_digest')!=source['source_digest']:raise web.HTTPConflict(text='8단계 경로가 변경되었습니다. 9단계를 다시 여세요.')
            previous_lane=digest(stages.get('9'))
            if data.get('enabled',True) is False:
                stages['9']={'enabled':False,'source_digest':source['source_digest'],'reference_point':source['reference_point'],'path_method':source['method']}
                if 'lane_width_m' in data:stages['9']['lane_width_m']=validate_lane_width(data['lane_width_m'])
            else:
                config=road_config('lane_width_m' not in data)
                width=validate_lane_width(data.get('lane_width_m',config.get('lane_width_m')))
                if data.get('road_digest')!=digest(config):raise web.HTTPConflict(text='차선 폭 설정이 변경되었습니다. 차선 적용을 다시 누르세요.')
                stages['9']=lane_settings(project,config,width)
            if 'projection' in data:
                view=data['projection']
                if not isinstance(view,dict) or type(view.get('enabled')) is not bool or type(view.get('time_offset_s')) not in (int,float) or not math.isfinite(view['time_offset_s']) or abs(view['time_offset_s'])>30:
                    raise web.HTTPBadRequest(text='영상 투영 설정과 시간 보정(-30~30초)을 확인하세요.')
                stages['9']['projection']={'enabled':view['enabled'],'time_offset_s':view['time_offset_s']}
                for key in ('show_lanes','show_center','show_sections'):
                    if key in view:
                        if type(view[key]) is not bool:raise web.HTTPBadRequest(text='영상 표시 설정은 체크 여부로 지정하세요.')
                        stages['9']['projection'][key]=view[key]
            if digest(stages['9'])!=previous_lane:invalidate(project,9)
        elif stage==10:
            result=section_result(project,data.get('sections'))
            if data.get('source_digest')!=result['source_digest']:raise web.HTTPConflict(text='예상 차선이 변경되었습니다. 10단계를 다시 여세요.')
            if digest(stages.get('10'))!=digest(result):invalidate(project,10)
            stages['10']=result
        elif stage==10.5:
            result=final_point_result(project,data.get('additions'))
            if data.get('source_digest')!=result['source_digest']:raise web.HTTPConflict(text='최종 경로가 변경되었습니다. 화면을 다시 여세요.')
            if digest(stages.get('10.5'))!=digest(result):invalidate(project,10.5)
            stages['10.5']=result
        elif stage==11:
            final_map(project)
            bag=data.get('bag');position=data.get('position_s',0)
            validated=data.get('validated_bags',[])
            if not isinstance(validated,list) or any(not isinstance(item,str) or not item.strip() for item in validated):raise web.HTTPBadRequest(text='검증한 로스백 목록을 확인하세요.')
            if bag is not None and not isinstance(bag,str):raise web.HTTPBadRequest(text='로스백 이름을 확인하세요.')
            if type(position) not in (int,float) or not math.isfinite(position) or position<0:raise web.HTTPBadRequest(text='재생 시각을 확인하세요.')
            invalidate(project,11)
            stages['11']={'source_digest':digest(stages['9']),'bag':bag,'position_s':position,'validated_bags':list(dict.fromkeys(validated)),'saved_at':datetime.now(timezone.utc).isoformat()}
        else:raise web.HTTPBadRequest(text='지원하지 않는 단계입니다.')
        project['revision']+=1;project['saved_at']=datetime.now(timezone.utc).isoformat()
        return refresh_write(name,project,stage) if data.get('refresh_name') else write(name,project)
    async def update_route(request):
        data=await body(request)
        async with lock:result=await asyncio.to_thread(update,data)
        return web.json_response(result)
    def rewind(data):
        name=data.get('filename');project=load(name)
        if data.get('revision')!=project['revision']:
            raise web.HTTPConflict(text='다른 화면에서 파일이 변경됐습니다. 파일을 다시 불러오세요.')
        target=data.get('stage')
        if type(target) not in (int,float) or target not in (1,2,2.5,3,4,5,6,7,8,9,10,10.5,11):raise web.HTTPBadRequest(text='이동할 앞 단계를 확인하세요.')
        if str(target) not in project['stages'] and not (target==2.5 and project['stages'].get('2',{}).get('map_merge')) and not (target==4 and '3' in project['stages']) and not (target in (10,10.5,11) and '9' in project['stages']):raise web.HTTPConflict(text='해당 단계의 저장 결과가 없습니다.')
        if target<=2:project.pop('map_merge_result',None)
        project['stages']={k:v for k,v in project['stages'].items() if float(k)<=target}
        # Remove downstream data from archived results as well, not just active stages.
        history=[]
        for entry in project.get('history',[]):
            entry={**entry,'stages':{k:v for k,v in entry.get('stages',{}).items() if float(k)<=target}}
            if entry['stages']:history.append(entry)
        if history:project['history']=history
        else:project.pop('history',None)
        project['revision']+=1;project['saved_at']=datetime.now(timezone.utc).isoformat()
        return refresh_write(name,project) if data.get('refresh_name') else write(name,project)
    async def rewind_route(request):
        data=await body(request)
        async with lock:result=await asyncio.to_thread(rewind,data)
        return web.json_response(result)
    async def editor(request):
        project=await asyncio.to_thread(load,request.query.get('filename',''))
        if '2' not in project['stages']:return web.json_response({'raw':None})
        raw=effective_raw(project) if request.query.get('step')=='points' else project['stages']['2']['raw']
        rv=await asyncio.to_thread(review,raw,project['stages'].get('3',{}).get('tracks') if request.query.get('step')=='points' else None)
        return web.json_response({'raw':raw,'review':rv},headers={'Cache-Control':'no-store'})
    async def preview(request):
        data=await body(request);project=await asyncio.to_thread(load,data.get('filename'))
        if '2' not in project['stages']:raise web.HTTPConflict(text='먼저 2단계를 저장하세요.')
        raw=project['stages']['2']['raw'] if data.get('step')=='bags' else effective_raw(project)
        if data.get('dataset_id')!=identify(raw)[1]:raise web.HTTPConflict(text='2단계 GPS가 변경되었습니다.')
        return web.json_response(await asyncio.to_thread(review,raw,data.get('tracks')))
    async def merge_preview(request):
        data=await body(request);project=await asyncio.to_thread(load,data.get('filename'))
        if data.get('source_digest')!=augmentation_digest(project):
            raise web.HTTPConflict(text='3단계 결과가 변경되었습니다. 병합 화면을 다시 여세요.')
        tracks=await asyncio.to_thread(merge_curves,augmented(project),data.get('tracks'))
        return web.json_response({'tracks':tracks})
    async def merge_source(request):
        project=await asyncio.to_thread(load,request.query.get('filename',''))
        return web.json_response({'source':augmented(project),'tracks':project['stages'].get('5',{}).get('tracks'), 'source_digest':augmentation_digest(project)},headers={'Cache-Control':'no-store'})
    async def additions_source(request):
        project=await asyncio.to_thread(load,request.query.get('filename',''))
        source=retained(project)
        saved=project['stages'].get('4')
        result=saved or addition_result(source,[],digest(project['stages']['3']))
        return web.json_response({'origin':source['origin'],'tracks':result['tracks'],'source_digest':digest(project['stages']['3'])},headers={'Cache-Control':'no-store'})
    async def fusion_source(request):
        project=await asyncio.to_thread(load,request.query.get('filename',''))
        return web.json_response({'points':source_points(project),'origin':project['stages']['2']['raw']['origin'],
            'source_digest':digest(project['stages']['5']),'saved':project['stages'].get('6')},headers={'Cache-Control':'no-store'})
    async def fusion_preview(request):
        data=await body(request);project=await asyncio.to_thread(load,data.get('filename'))
        if data.get('source_digest')!=digest(project['stages'].get('5')):raise web.HTTPConflict(text='5단계 결과가 변경되었습니다. 6단계를 다시 여세요.')
        tracks=await asyncio.to_thread(fusion_curves,source_points(project),data.get('groups'),project['stages']['2']['raw']['origin'])
        return web.json_response({'tracks':tracks})
    async def fusion_auto(request):
        data=await body(request);project=await asyncio.to_thread(load,data.get('filename'))
        if data.get('source_digest')!=digest(project['stages'].get('5')):raise web.HTTPConflict(text='5단계 결과가 변경되었습니다. 6단계를 다시 여세요.')
        groups=await asyncio.to_thread(automatic_groups,source_points(project),data.get('groups'),data.get('selected'),data.get('radius_m'),project['stages']['2']['raw']['origin'])
        return web.json_response({'groups':groups})
    async def order_source(request):
        project=await asyncio.to_thread(load,request.query.get('filename',''))
        source=await asyncio.to_thread(ordering_source,project)
        return web.json_response({**source,'source_digest':digest(project['stages']['6']),'saved':project['stages'].get('7')},headers={'Cache-Control':'no-store'})
    async def order_auto(request):
        data=await body(request);project=await asyncio.to_thread(load,data.get('filename'))
        if data.get('source_digest')!=digest(project['stages'].get('6')):raise web.HTTPConflict(text='6단계 결과가 변경되었습니다. 7단계를 다시 여세요.')
        result=await asyncio.to_thread(automatic_order,project,data.get('reference_id'),data.get('max_distance_m'))
        return web.json_response(result)
    async def final_source(request):
        project=await asyncio.to_thread(load,request.query.get('filename',''))
        source=await asyncio.to_thread(path_source,project)
        vehicle=await asyncio.to_thread(vehicle_config)
        return web.json_response({**source,'method':PATH_METHOD,'vehicle':vehicle,'vehicle_digest':digest(vehicle),'saved':single_path_result(project['stages']['8']) if '8' in project['stages'] else None},headers={'Cache-Control':'no-store'})
    async def final_preview(request):
        data=await body(request)
        if path_lock.locked():raise web.HTTPConflict(text='경로 계산이 진행 중입니다. 잠시 후 다시 시도하세요.')
        async with path_lock:
            project=await asyncio.to_thread(load,data.get('filename'))
            if data.get('source_digest')!=digest(project['stages'].get('7')):raise web.HTTPConflict(text='7단계 결과가 변경되었습니다. 8단계를 다시 여세요.')
            vehicle=await asyncio.to_thread(vehicle_config)
            result=await asyncio.to_thread(generate_path,project,vehicle,data.get('settings'),data.get('waypoints'))
            token=uuid.uuid4().hex
            path_previews[token]={'filename':data['filename'],'result':result}
            while len(path_previews)>8:path_previews.popitem(last=False)
            return web.json_response({'preview_id':token,'result':result})
    async def projection_configuration(request):
        return web.json_response(await asyncio.to_thread(projection_config),headers={'Cache-Control':'no-store'})
    async def estimated_lane_source(request):
        project=await asyncio.to_thread(load,request.query.get('filename',''))
        source=await asyncio.to_thread(lane_source,project)
        saved=project['stages'].get('9')
        if saved and saved['source_digest']!=source['source_digest']:saved=None
        final = final_map(project) if request.query.get('final') == '1' else None
        if final:source={**source,'points':final['points'],'statistics':{'point_count':len(final['points']),'length_m':final['points'][-1]['s_m']}}
        try:
            config=await asyncio.to_thread(road_config,False);error=None
        except web.HTTPBadRequest as exc:
            config=None;error=exc.text
        try:
            vehicle=await asyncio.to_thread(vehicle_display_config);vehicle_error=None
        except web.HTTPBadRequest as exc:
            vehicle=None;vehicle_error=exc.text
        edges=lane_edges(source['points'],saved['lane_width_m']) if saved and saved.get('enabled',True) else None
        return web.json_response({**source,'task_sections':final['task_sections'] if final else (project['stages'].get('10',{}).get('sections',[]) if saved and project['stages'].get('10',{}).get('source_digest')==digest(saved) else []),'vehicle':vehicle,'vehicle_error':vehicle_error,'road_config':config,'road_error':error,'saved':saved,'edges':edges},headers={'Cache-Control':'no-store'})
    async def final_waypoint_source(request):
        project=await asyncio.to_thread(load,request.query.get('filename',''))
        final=final_map(project)
        return web.json_response({**final_point_source(project),'final_points':final['points']},headers={'Cache-Control':'no-store'})
    async def task_section_source(request):
        project=await asyncio.to_thread(load,request.query.get('filename',''))
        source=section_source(project)
        try:
            source['vehicle']=await asyncio.to_thread(vehicle_display_config)
        except web.HTTPBadRequest:
            source['vehicle']=None
        return web.json_response(source,headers={'Cache-Control':'no-store'})
    async def estimated_lane_preview(request):
        data=await body(request);project=await asyncio.to_thread(load,data.get('filename'))
        source=lane_source(project)
        if data.get('source_digest')!=source['source_digest']:raise web.HTTPConflict(text='8단계 경로가 변경되었습니다. 9단계를 다시 여세요.')
        config=await asyncio.to_thread(road_config,'lane_width_m' not in data)
        width=validate_lane_width(data.get('lane_width_m',config.get('lane_width_m')))
        return web.json_response({'settings':lane_settings(project,config,width),'edges':lane_edges(source['points'],width)})
    def export_final(data):
        name=valid_name(data.get('filename'));new_name=valid_name(data.get('new_filename'))
        project=load(name)
        if data.get('revision')!=project['revision']:raise web.HTTPConflict(text='파일이 변경됐습니다. 다시 불러오세요.')
        exported=final_map(project)
        if new_name!=name and (directory()/new_name).exists():raise web.HTTPConflict(text='이미 있는 파일 이름입니다.')
        suffix=user_suffix(new_name)
        now=datetime.now(ZoneInfo('Asia/Seoul'))
        new_name=valid_name(f"{display_stage(project,12)}단계_{now:%Y-%m-%d_%H%M%S}_{suffix}.json")
        if (directory()/new_name).exists():new_name=valid_name(f"{display_stage(project,12)}단계_{now:%Y-%m-%d_%H%M%S%f}_{suffix}.json")
        export_name=valid_name(f"MAP_{now:%Y-%m-%d_%H%M%S}_{suffix}.json")
        if (directory()/export_name).exists() or export_name==new_name:
            export_name=valid_name(f"MAP_{now:%Y-%m-%d_%H%M%S%f}_{user_suffix(new_name)}.json")
        project['stages']['12']={'source_digest':digest(project['stages']['9']),'export_filename':export_name,'saved_at':now.isoformat()}
        renamed=False;created=False
        try:
            if new_name!=name:
                project['revision']+=1;project['saved_at']=datetime.now(timezone.utc).isoformat()
                write(new_name,project,True);renamed=True
            output=write(export_name,exported,True);created=True
            if renamed:(directory()/name).unlink()
        except BaseException:
            if created:(directory()/export_name).unlink(missing_ok=True)
            if renamed:(directory()/new_name).unlink(missing_ok=True)
            raise
        return {'working':response(new_name,project),'export':{k:v for k,v in output.items() if k!='project'}}
    async def export_route(request):
        data=await body(request)
        async with lock:result=await asyncio.to_thread(export_final,data)
        return web.json_response(result)
    def competition_status(category):
        if category not in ('preliminary','final'):
            raise web.HTTPBadRequest(text='예선 또는 본선 맵을 선택하세요.')
        filename=f'MAP_{category}.json';path=directory()/filename
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise web.HTTPConflict(text='맵 저장 위치가 일반 파일이 아닙니다.')
        content=path.read_bytes() if path.exists() else None
        return {'filename':filename,'exists':content is not None,
                'digest':hashlib.sha256(content).hexdigest() if content is not None else None,
                'workspace_path':'main/decision/script/map_generator/test/review/maps/'+filename}
    async def competition_read(request):
        result=await asyncio.to_thread(competition_status,request.query.get('category'))
        return web.json_response(result,headers={'Cache-Control':'no-store'})
    def competition_write(data):
        expected=data.get('expected_digest')
        if 'expected_digest' not in data or (expected is not None and (not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected))):
            raise web.HTTPBadRequest(text='기존 맵 파일을 확인한 뒤 저장하세요.')
        target=competition_status(data.get('category'))
        if target['digest']!=expected:
            raise web.HTTPConflict(text='기존 맵 파일이 변경되었습니다. 덮어쓰기 안내를 다시 확인하세요.')
        source=directory()/valid_name(data.get('source_filename'))
        if not source.name.startswith('MAP_') or source.is_symlink() or not source.is_file():
            raise web.HTTPBadRequest(text='저장된 최종 Map 파일을 선택하세요.')
        content=source.read_bytes()
        if json.loads(content).get('format')!='gps-final-map':
            raise web.HTTPBadRequest(text='최종 Map 파일만 추가 저장할 수 있습니다.')
        # Copy the exact exported bytes; replace atomically so readers see a complete map.
        temporary=None
        try:
            with tempfile.NamedTemporaryFile('wb',dir=directory(),delete=False) as f:
                temporary=Path(f.name);f.write(content);f.flush();os.fsync(f.fileno())
            temporary.chmod(0o664)
            temporary.replace(directory()/target['filename'])
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
        return {'filename':target['filename'],'workspace_path':target['workspace_path'],'overwritten':target['exists']}
    async def competition_save(request):
        data=await body(request)
        async with lock:result=await asyncio.to_thread(competition_write,data)
        return web.json_response(result)
    app.router.add_get('/api/gps/projects/competition-map',competition_read)
    app.router.add_post('/api/gps/projects/competition-map',competition_save)
    app.router.add_get('/api/gps/projects/section-source',task_section_source)
    app.router.add_post('/api/gps/projects/export',export_route)
    app.router.add_get('/api/gps/projects/projection-config',projection_configuration)
    app.router.add_get('/api/gps/projects/lane-source',estimated_lane_source)
    app.router.add_get('/api/gps/projects/final-waypoint-source',final_waypoint_source)
    app.router.add_post('/api/gps/projects/lane-preview',estimated_lane_preview)
    app.router.add_get('/api/gps/projects/path-source',final_source)
    app.router.add_post('/api/gps/projects/path-preview',final_preview)
    app.router.add_get('/api/gps/projects',listing)
    app.router.add_get('/api/gps/projects/load',read)
    app.router.add_post('/api/gps/projects/create',create_route)
    app.router.add_post('/api/gps/projects/resume',resume_route)
    app.router.add_post('/api/gps/projects/save',update_route)
    app.router.add_post('/api/gps/projects/rewind',rewind_route)
    app.router.add_get('/api/gps/projects/editor',editor)
    app.router.add_post('/api/gps/projects/preview',preview)
    app.router.add_get('/api/gps/projects/additions-source',additions_source)
    app.router.add_get('/api/gps/projects/merge-source',merge_source)
    app.router.add_get('/api/gps/projects/fusion-source',fusion_source)
    app.router.add_get('/api/gps/projects/order-source',order_source)
    app.router.add_post('/api/gps/projects/order-auto',order_auto)
    app.router.add_post('/api/gps/projects/fusion-auto',fusion_auto)
    app.router.add_post('/api/gps/projects/fusion-preview',fusion_preview)
    app.router.add_post('/api/gps/projects/merge-preview',merge_preview)
