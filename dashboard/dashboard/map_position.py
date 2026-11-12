"""Read-only map points for comparing a saved map with the current GNSS fix."""
import asyncio
import json
import math
from pathlib import Path
from aiohttp import web
from .gps_project import directory


def map_points(document):
    source='저장 GPS';ordered=True
    if isinstance(document.get('points'),list):
        points=document['points']
    elif document.get('format')=='gps-map-project':
        stages=document.get('stages',{})
        path=stages.get('8',{})
        if path.get('points'):
            points=path['points'];source='8단계 저장 경로'
        elif path.get('waypoints') and stages.get('7',{}).get('ordered_points'):
            from .gps_path import path_source
            points=path_source(document)['points'];source='8단계 웨이포인트'
        elif stages.get('7',{}).get('ordered_points'):
            points=stages['7']['ordered_points'];source='7단계 순서 GPS'
        elif stages.get('6',{}).get('points'):
            points=stages['6']['points'];source='6단계 GPS (파일 순서)';ordered=False
        else:
            tracks=next((stages[k]['tracks'] for k in ('5','4','3') if stages.get(k,{}).get('tracks')),
                        stages.get('2',{}).get('raw',{}).get('tracks',[]))
            points=flatten(tracks);source='저장 GPS (파일 순서)';ordered=False
    else:
        points=flatten(document.get('tracks',[]));ordered=False
    if not points:raise ValueError('표시할 GPS 포인트가 없습니다. GPS가 저장된 파일을 선택하세요.')
    if len(points)>200000:raise ValueError('표시 가능한 GPS는 최대 200,000점입니다.')
    checked=[]
    for i,p in enumerate(points):
        if not isinstance(p,dict):raise ValueError('GPS 포인트 형식이 올바르지 않습니다.')
        lat,lon=p.get('lat'),p.get('lon')
        if (any(type(v) not in (int,float) or not math.isfinite(v) for v in (lat,lon)) or
                not -90<=lat<=90 or not -180<=lon<=180):
            raise ValueError(f'{i+1}번째 GPS 좌표가 올바르지 않습니다.')
        checked.append({'index':i+1,'lat':lat,'lon':lon,
                        'break_before':bool(p.get('break_before',False))})
    return {'points':checked,'point_count':len(checked),'source':source,'ordered':ordered,
            'start':checked[0],'end':checked[-1]}


def flatten(tracks):
    points=[]
    for track in tracks:
        for i,p in enumerate(track.get('points',track.get('retained_points',[]))):
            points.append({**p,'break_before':bool(p.get('break_before')) or (i==0 and bool(points))})
    return points


def add_routes(app):
    def allowed(path):
        return path.suffix=='.json' and not path.is_symlink() and path.is_file()

    async def listing(request):
        def names():
            return sorted(p.name for p in directory().glob('*.json') if allowed(p))
        return web.json_response({'maps':await asyncio.to_thread(names)},headers={'Cache-Control':'no-store'})

    async def load(request):
        name=request.match_info['name']
        if Path(name).name!=name or '/' in name or '\\' in name or name.startswith('.'):
            raise web.HTTPNotFound()
        def read():
            path=directory()/name
            if not allowed(path):raise FileNotFoundError(name)
            document=json.loads(path.read_text())
            if not isinstance(document,dict):raise ValueError('지도 JSON 객체가 필요합니다.')
            if document.get('format')=='gps-map-project' and document.get('version',1)<3:
                from .gps_project import load as load_project
                document=load_project(name)
            return {'filename':name,**map_points(document)}
        try:
            data=await asyncio.to_thread(read)
        except FileNotFoundError:raise web.HTTPNotFound(text='지도 파일을 찾을 수 없습니다.')
        except PermissionError:raise web.HTTPForbidden(text='지도 파일을 읽을 수 없습니다.')
        except (ValueError,TypeError,KeyError,AttributeError) as error:
            raise web.HTTPBadRequest(text='지도를 불러올 수 없습니다: '+str(error))
        return web.json_response(data,headers={'Cache-Control':'no-store'})

    app.router.add_get('/api/map-position/maps',listing)
    app.router.add_get('/api/map-position/maps/{name}',load)
