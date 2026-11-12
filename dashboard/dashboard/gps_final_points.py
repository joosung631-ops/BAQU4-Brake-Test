"""Insert explicit final samples without smoothing or resampling the saved path."""
import copy
import math
import re
from aiohttp import web
from .gps_lane import lane_source
from .gps_review import digest, project


def final_point_source(document):
    source = lane_source(document)
    lane = document['stages'].get('9')
    if not lane or lane.get('source_digest') != source['source_digest']:
        raise web.HTTPConflict(text='먼저 예상 차선 적용 결과를 저장하세요.')
    identity = digest({key: document['stages'].get(key) for key in ('9', '10')})
    return {**source, 'source_digest': identity, 'saved': document['stages'].get('10.5')}


def final_point_result(document, additions):
    source = final_point_source(document)
    if not isinstance(additions, list) or len(additions) > 10000:
        raise web.HTTPBadRequest(text='추가 웨이포인트는 최대 10,000개입니다.')
    count = len(source['points']) + len(additions)
    ids, indices, clean = set(), set(), []
    for item in additions:
        if not isinstance(item, dict):
            raise web.HTTPBadRequest(text='추가 웨이포인트 형식을 확인하세요.')
        key, index, lat, lon = (item.get(k) for k in ('id', 'index', 'lat', 'lon'))
        if not isinstance(key, str) or not re.fullmatch(r'final-[a-zA-Z0-9_-]{1,80}', key) or key in ids:
            raise web.HTTPBadRequest(text='추가 웨이포인트 ID가 잘못되었거나 중복되었습니다.')
        if type(index) is not int or not 1 <= index <= count or index in indices:
            raise web.HTTPBadRequest(text=f'순번은 중복 없이 1~{count} 사이 정수로 입력하세요.')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise web.HTTPBadRequest(text='올바른 위도(-90~90)와 경도(-180~180)를 입력하세요.')
        ids.add(key); indices.add(index)
        clean.append({'id':key, 'index':index, 'lat':lat, 'lon':lon})
    return {'source_digest':source['source_digest'], 'additions':sorted(clean, key=lambda p:p['index'])}


def apply_final_points(document, points, sections):
    saved = document['stages'].get('10.5')
    if not saved:
        return points, sections
    result = final_point_result(document, saved.get('additions'))
    if saved.get('source_digest') != result['source_digest']:
        raise web.HTTPConflict(text='차선 또는 과제 구간이 변경되었습니다. 최종 웨이포인트 추가를 다시 저장하세요.')
    if not result['additions']:
        return points, sections
    by_index = {p['index']:p for p in result['additions']}
    projected = {p['index']:p for p in project(result['additions'], document['stages']['2']['raw']['origin'])}
    base, output, base_indices = iter(points), [], []
    for index in range(1, len(points)+len(by_index)+1):
        if index in by_index:
            p = projected[index]
            output.append({k:p[k] for k in ('e','n','lat','lon')})
        else:
            output.append(copy.deepcopy(next(base))); base_indices.append(index-1)
    station = 0.
    for i, p in enumerate(output):
        if i: station += math.hypot(p['e']-output[i-1]['e'], p['n']-output[i-1]['n'])
        a, b = (p, output[i+1]) if i+1<len(output) else (output[i-1], p)
        p.update(index=i+1, s_m=station, heading_rad=math.atan2(b['n']-a['n'],b['e']-a['e']))
        p.pop('curvature_per_m', None); p.pop('steering_deg', None)
    remapped = copy.deepcopy(sections)
    for section in remapped:
        for name in ('start', 'end'):
            mark = section[name]; old = mark['segment_index']
            lo, hi = base_indices[old:old+2]
            best = None
            for i in range(lo, hi):
                a, b = output[i:i+2]; dx, dy = b['e']-a['e'], b['n']-a['n']
                t = max(0., min(1., ((mark['center']['e']-a['e'])*dx+(mark['center']['n']-a['n'])*dy)/(dx*dx+dy*dy or 1.)))
                distance = (a['e']+t*dx-mark['center']['e'])**2+(a['n']+t*dy-mark['center']['n'])**2
                candidate = (distance, i, t)
                if best is None or candidate < best: best = candidate
            _, i, t = best
            mark.update(segment_index=i, fraction=t, s_m=output[i]['s_m']+(output[i+1]['s_m']-output[i]['s_m'])*t)
    return output, remapped
