"""Local GPS review persistence and distance-parameterized smooth curves.

Uniform arc-length samples remove dwell-time weighting. Penalized second
 differences smooth each coordinate; a natural cubic spline renders the result.
No curve is fitted across a recorded GPS gap or across bags.
"""
import asyncio
from bisect import bisect_right
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from aiohttp import web
from .gps_workflow import save_snapshot, stage_one, valid_name, directory as stage_directory


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def identify(raw):
    tracks = []
    for track in raw['tracks']:
        identity = {'name': track['name'], 'points': [
            {k: p.get(k) for k in ('seq', 'lat', 'lon', 'recorded_ns', 'break_before')}
            for p in track['points']]}
        tracks.append({**track, 'id': digest(identity)})
    return tracks, digest([t['id'] for t in tracks])


def project(points, origin):
    def xyz(lat, lon):
        lat, lon = math.radians(lat), math.radians(lon)
        e2 = 6.6943799901413165e-3
        n = 6378137 / math.sqrt(1-e2*math.sin(lat)**2)
        return n*math.cos(lat)*math.cos(lon), n*math.cos(lat)*math.sin(lon), n*(1-e2)*math.sin(lat)
    a, b = map(math.radians, origin)
    base = xyz(*origin)
    result = []
    for p in points:
        x, y, z = [v-u for v, u in zip(xyz(p['lat'], p['lon']), base)]
        result.append({**p, 'e': -math.sin(b)*x+math.cos(b)*y,
                       'n': -math.sin(a)*math.cos(b)*x-math.sin(a)*math.sin(b)*y+math.cos(a)*z})
    return result


def smooth(values, strength):
    """Solve min ||z-y||² + strength ||D²z||² using banded Cholesky."""
    n = len(values)
    if n < 3 or strength == 0:
        return list(values)
    a0, a1, a2 = [1.]*n, [0.]*n, [0.]*n
    for i in range(n-2):
        a0[i] += strength; a0[i+1] += 4*strength; a0[i+2] += strength
        a1[i+1] -= 2*strength; a1[i+2] -= 2*strength; a2[i+2] += strength
    d, l1, l2, y = [0.]*n, [0.]*n, [0.]*n, [0.]*n
    for i in range(n):
        if i >= 2: l2[i] = a2[i]/d[i-2]
        if i >= 1: l1[i] = (a1[i]-l2[i]*l1[i-1])/d[i-1]
        d[i] = math.sqrt(a0[i]-l1[i]**2-l2[i]**2)
        y[i] = (values[i]-(l1[i]*y[i-1] if i else 0)-(l2[i]*y[i-2] if i>1 else 0))/d[i]
    z = [0.]*n
    for i in range(n-1, -1, -1):
        z[i] = (y[i]-(l1[i+1]*z[i+1] if i+1<n else 0)-(l2[i+2]*z[i+2] if i+2<n else 0))/d[i]
    return z


def natural_seconds(values, h):
    n = len(values)
    result = [0.]*n
    c, d = [0.]*n, [0.]*n
    for i in range(1, n-1):
        denominator = 4-c[i-1]
        c[i] = 1/denominator
        rhs = 6*(values[i+1]-2*values[i]+values[i-1])/h**2
        d[i] = (rhs-d[i-1])/denominator
    for i in range(n-2, 0, -1): result[i] = d[i]-c[i]*result[i+1]
    return result


def curve_segment(points, length):
    unique = []
    for p in points:
        if not unique or math.hypot(p['e']-unique[-1]['e'],p['n']-unique[-1]['n'])>1e-5:
            unique.append(p)
    if len(unique)<2:
        return [{k:p[k] for k in ('e','n','seq')} for p in unique]
    distance = [0.]
    for a,b in zip(unique,unique[1:]): distance.append(distance[-1]+math.hypot(a['e']-b['e'],a['n']-b['n']))
    total = distance[-1]
    count = min(4000, max(2, math.ceil(total/.5)+1))
    h = total/(count-1)
    def at(s, key):
        i = min(len(unique)-2,max(0,bisect_right(distance,s)-1))
        f = (s-distance[i])/(distance[i+1]-distance[i])
        return unique[i][key]*(1-f)+unique[i+1][key]*f
    axes = [smooth([at(i*h,k) for i in range(count)], (length/h)**4) for k in ('e','n')]
    seconds = [natural_seconds(axis,h) for axis in axes]
    result = []
    for j in range(2*(count-1)+1):
        u = j/2; i = min(count-2,int(u)); b = u-i; a = 1-b
        xy = [a*v[i]+b*v[i+1]+((a**3-a)*m[i]+(b**3-b)*m[i+1])*h*h/6
              for v,m in zip(axes,seconds)]
        result.append({'e':xy[0], 'n':xy[1], 'seq':at(u*h,'seq')})
    return result


def build_review(track, origin, excluded, smoothing, complete=False, start_seq=None, end_seq=None):
    valid = {p['seq'] for p in track['points']}
    if (not isinstance(excluded,list) or any(type(i) is not int for i in excluded)
            or not set(excluded)<=valid):
        raise ValueError('제외 순번이 원본 기록과 일치하지 않습니다.')
    if type(smoothing) not in (float,int) or not math.isfinite(smoothing) or not 0<=smoothing<=10:
        raise ValueError('매끄러움은 0~10m 사이여야 합니다.')
    if type(complete) is not bool: raise ValueError('검토 완료 값이 잘못되었습니다.')
    for bound in (start_seq,end_seq):
        if bound is not None and (type(bound) is not int or bound not in valid):
            raise ValueError('시작·끝 순번이 원본 기록과 일치하지 않습니다.')
    if start_seq is not None and end_seq is not None and start_seq>end_seq:
        raise ValueError('시작 순번은 끝 순번보다 클 수 없습니다.')
    manual_excluded = set(excluded)
    excluded = manual_excluded | {seq for seq in valid
        if (start_seq is not None and seq<start_seq) or (end_seq is not None and seq>end_seq)}
    segments, current = [], []
    for p in project(track['points'],origin):
        if p.get('break_before'):
            if current: segments.append(current)
            current = []
        if p['seq'] not in excluded: current.append(p)
    if current: segments.append(current)
    retained = [{k:p[k] for k in ('seq','lat','lon')} for p in track['points'] if p['seq'] not in excluded]
    return {'id':track['id'], 'name':track['name'], 'excluded_seq':sorted(excluded),
            'manual_excluded_seq':sorted(manual_excluded), 'start_seq':start_seq, 'end_seq':end_seq,
            'smoothing_m':smoothing, 'complete':complete, 'retained_points':retained,
            'curve_segments':[curve_segment(segment,smoothing) for segment in segments]}


def add_routes(app):
    root = Path(os.environ.get('DASHBOARD_GPS_MAP_DIR',
                Path(__file__).resolve().parents[2]/'main/decision/script/map_generator'))
    directory = Path(os.environ.get('DASHBOARD_GPS_REVIEW_DIR',root/'test'/'review'))
    destination = directory/'review.json'
    lock = asyncio.Lock()

    def source():
        raw = json.loads((root/'test'/'raw.json').read_text())
        tracks, dataset = identify(raw)
        return raw, tracks, dataset

    def stored():
        return json.loads(destination.read_text()) if destination.exists() else {'revision':0,'tracks':{}}

    def snapshot():
        raw, tracks, dataset = source(); saved = stored()
        result = []
        for track in tracks:
            prior = saved['tracks'].get(track['id'],{})
            result.append(build_review(track,raw['origin'],prior.get('manual_excluded_seq',prior.get('excluded_seq',[])),
                                       prior.get('smoothing_m',.5),prior.get('complete',False),
                                       prior.get('start_seq'),prior.get('end_seq')))
        return {'dataset_id':dataset, 'revision':saved['revision'], 'origin':raw['origin'],
                'saved_at':saved.get('saved_at'), 'tracks':result}

    async def read(request):
        return web.json_response(await asyncio.to_thread(snapshot),headers={'Cache-Control':'no-store'})

    async def body(request):
        if request.headers.get('X-Dashboard-Control')!='1' or request.content_type!='application/json':
            raise web.HTTPForbidden()
        try:
            data = await request.json()
            if not isinstance(data,dict): raise ValueError()
            return data
        except ValueError: raise web.HTTPBadRequest(text='잘못된 요청입니다.')

    def calculate(data):
        raw, tracks, dataset = source()
        if data.get('dataset_id')!=dataset:
            raise web.HTTPConflict(text='원본 기록이 변경되었습니다. 원본을 다시 불러오세요.')
        known = {t['id']:t for t in tracks}
        specs = data.get('tracks')
        if not isinstance(specs,list) or not specs or len(specs)>len(tracks):
            raise web.HTTPBadRequest(text='검토할 기록을 지정하세요.')
        results = []
        for spec in specs:
            if not isinstance(spec,dict) or spec.get('id') not in known:
                raise web.HTTPBadRequest(text='알 수 없는 기록입니다.')
            try:
                results.append(build_review(known[spec['id']],raw['origin'],spec.get('excluded_seq',[]),
                                            spec.get('smoothing_m',.5),spec.get('complete',False),
                                            spec.get('start_seq'),spec.get('end_seq')))
            except ValueError as error: raise web.HTTPBadRequest(text=str(error))
        if len({t['id'] for t in results})!=len(results): raise web.HTTPBadRequest(text='중복 기록입니다.')
        return raw, dataset, results

    async def preview(request):
        data = await body(request)
        _, _, results = await asyncio.to_thread(calculate,data)
        return web.json_response({'tracks':results})

    def write(data):
        raw, dataset, results = calculate(data)
        previous = stored()
        if data.get('revision')!=previous['revision']:
            raise web.HTTPConflict(text='다른 화면에서 저장한 변경이 있습니다. 새로고침 전에 현재 선택을 확인하세요.')
        if data.get('filename') is not None:
            name = valid_name(data['filename'])
            if (stage_directory()/name).exists():
                raise web.HTTPConflict(text='같은 이름의 파일이 있습니다. 파일 이름을 바꿔주세요.')
        previous.update({'format':'gps-point-review','version':1,'dataset_id':dataset,
                         'origin':raw['origin'],'revision':previous['revision']+1,
                         'saved_at':datetime.now(timezone.utc).isoformat(),
                         'curve_method':'uniform-arc second-difference smoothing + natural cubic'})
        # Keep reviews for older/temporarily removed recordings, identified by source hash.
        for result in results: previous['tracks'][result['id']]={**result,'origin':raw['origin']}
        directory.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile('w',dir=directory,encoding='utf-8',delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(previous,stream,ensure_ascii=False,allow_nan=False,indent=2)
                stream.flush();os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True);raise
        exported = {}
        try:
            if data.get('filename') is not None:
                exported = save_snapshot(data['filename'],stage_one({**raw,'tracks':identify(raw)[0]},dataset,results))
            temporary.chmod(0o664);temporary.replace(destination)
        except BaseException:
            if exported: Path(exported['path']).unlink(missing_ok=True)
            raise
        finally: temporary.unlink(missing_ok=True)
        return {'revision':previous['revision'],'saved_at':previous['saved_at'],**exported}

    async def save(request):
        data = await body(request)
        async with lock:
            result = await asyncio.to_thread(write,data)
        return web.json_response(result)

    app.router.add_get('/api/gps/review',read)
    app.router.add_post('/api/gps/review/preview',preview)
    app.router.add_post('/api/gps/review',save)
