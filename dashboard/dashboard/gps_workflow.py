"""Named, immutable stage snapshots and explicit per-recording point merging."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from aiohttp import web


def directory():
    root = Path(os.environ.get('DASHBOARD_GPS_MAP_DIR', Path(__file__).resolve().parents[2]/'main/decision/script/map_generator'))
    return Path(os.environ.get('DASHBOARD_GPS_REVIEW_DIR', root/'test/review'))/'stages'


def valid_name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[\w가-힣 .()-]{1,150}\.json', name) or name.startswith('.'):
        raise web.HTTPBadRequest(text='파일 이름은 150자 이내로 입력하세요. 경로 구분자는 사용할 수 없습니다.')
    return name


def save_snapshot(name, data):
    name = valid_name(name)
    folder = directory(); folder.mkdir(parents=True, exist_ok=True)
    path = folder/name
    data = {**data, 'saved_at': datetime.now(timezone.utc).isoformat()}
    with tempfile.NamedTemporaryFile('w', dir=folder, encoding='utf-8', delete=False) as f:
        temporary = Path(f.name)
        try:
            json.dump(data, f, ensure_ascii=False, allow_nan=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True); raise
    try:
        temporary.chmod(0o664)
        os.link(temporary, path)  # Atomic creation, never overwrite an earlier snapshot.
    except FileExistsError:
        raise web.HTTPConflict(text='같은 이름의 파일이 있습니다. 파일 이름을 바꿔주세요.')
    finally:
        temporary.unlink(missing_ok=True)
    return {'filename': name, 'path': str(path), 'workspace_path': 'main/decision/script/map_generator/test/review/stages/'+name}


def load_snapshot(name):
    path = directory()/valid_name(name)
    if not path.is_file(): raise web.HTTPNotFound(text='저장 파일을 찾을 수 없습니다.')
    data = json.loads(path.read_text())
    if data.get('format') != 'gps-workflow' or data.get('stage') not in (1, 2):
        raise web.HTTPBadRequest(text='GPS 단계 파일이 아닙니다.')
    return data


def stage_one(raw, dataset, results):
    tracks = []
    for original, review in ((t, r) for t in raw['tracks'] for r in results if t['id'] == r['id']):
        kept = {p['seq'] for p in review['retained_points']}
        segment = 0; points = []
        for p in original['points']:
            if p.get('break_before'): segment += 1
            if p['seq'] in kept:
                points.append({'seq': p['seq'], 'lat': p['lat'], 'lon': p['lon'], 'segment': segment})
        tracks.append({'id': review['id'], 'name': review['name'], 'points': points,
                       'excluded_seq': review['excluded_seq'], 'start_seq': review['start_seq'], 'end_seq': review['end_seq']})
    return {'format': 'gps-workflow', 'version': 1, 'stage': 1, 'dataset_id': dataset, 'origin': raw['origin'], 'tracks': tracks}


def merge_tracks(source, specs):
    if not isinstance(specs, list) or len(specs) != len(source['tracks']):
        raise web.HTTPBadRequest(text='모든 기록의 병합 상태가 필요합니다.')
    output = []
    for track, spec in zip(source['tracks'], specs):
        if not isinstance(spec, dict) or spec.get('id') != track['id']:
            raise web.HTTPBadRequest(text='기록이 원본과 일치하지 않습니다.')
        original = track['points']; by_seq = {p['seq']: p for p in original}
        groups = spec.get('groups')
        if not isinstance(groups, list) or any(not isinstance(g, list) or not g or any(type(s) is not int for s in g) for g in groups):
            raise web.HTTPBadRequest(text='잘못된 병합 그룹입니다.')
        if [s for g in groups for s in g] != [p['seq'] for p in original]:
            raise web.HTTPBadRequest(text='같은 기록에서 순서상 이어지는 점만 병합할 수 있습니다.')
        points = []
        for group in groups:
            selected = [by_seq[s] for s in group]
            if len({p['segment'] for p in selected}) != 1:
                raise web.HTTPBadRequest(text='GPS 기록이 끊긴 구간을 넘어 병합할 수 없습니다.')
            points.append({'seq': group[0], 'source_seqs': group, 'count': len(group),
                           'lat': sum(p['lat'] for p in selected)/len(group),
                           'lon': sum(p['lon'] for p in selected)/len(group), 'segment': selected[0]['segment']})
        output.append({'id': track['id'], 'name': track['name'], 'groups': groups, 'points': points})
    return output


def add_routes(app):
    async def files(request):
        entries = []
        for path in sorted(directory().glob('*.json'), reverse=True):
            try:
                data = await asyncio.to_thread(load_snapshot, path.name)
                entries.append({'filename': path.name, 'stage': data['stage']})
            except (ValueError, web.HTTPException): continue
        return web.json_response({'files': entries}, headers={'Cache-Control': 'no-store'})

    async def load(request):
        name = request.query.get('filename', '')
        data = await asyncio.to_thread(load_snapshot, name)
        source = data if data['stage'] == 1 else await asyncio.to_thread(load_snapshot, data['source_file'])
        return web.json_response({'data': data, 'source': source, 'source_file': name if data['stage']==1 else data['source_file']}, headers={'Cache-Control': 'no-store'})

    async def save(request):
        if request.headers.get('X-Dashboard-Control') != '1' or request.content_type != 'application/json': raise web.HTTPForbidden()
        try: data = await request.json()
        except ValueError: raise web.HTTPBadRequest(text='잘못된 요청입니다.')
        if not isinstance(data, dict): raise web.HTTPBadRequest()
        source = await asyncio.to_thread(load_snapshot, data.get('source_file'))
        if source['stage'] != 1: raise web.HTTPBadRequest(text='1단계 원본 파일이 필요합니다.')
        tracks = merge_tracks(source, data.get('tracks'))
        result = await asyncio.to_thread(save_snapshot, data.get('filename'), {
            'format': 'gps-workflow', 'version': 1, 'stage': 2, 'source_file': data['source_file'],
            'origin': source['origin'], 'tracks': tracks})
        return web.json_response(result)

    app.router.add_get('/api/gps/stages', files)
    app.router.add_get('/api/gps/stages/load', load)
    app.router.add_post('/api/gps/stages/merge', save)
