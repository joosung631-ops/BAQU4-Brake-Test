"""Rotate and translate copied GPS intervals without modifying the saved source recordings."""
import math
import re
from aiohttp import web
from .gps_review import identify, project


def effective_raw(document):
    source = document['stages']['2']
    if not source.get('map_merge'):
        return source['raw']
    saved = document.get('map_merge_result')
    raw = saved['raw'] if saved and saved['source_dataset_id'] == source['dataset_id'] else source['raw']
    # Reference recordings are a display layer, never a path-generation input.
    return {**raw, 'tracks': [t for t in raw['tracks'] if t.get('map_merge_clip')], 'selected_bags': []}


def upgrade_reference_background(document):
    """Migrate prior combined inputs in memory; keep archived work for recovery."""
    source = document.get('stages', {}).get('2', {})
    if not source.get('map_merge'):
        return
    saved = document.get('map_merge_result')
    legacy = bool(saved and saved.get('version', 1) < 2)
    if legacy:
        raw = effective_raw(document)
        _, dataset = identify(raw)
        document['map_merge_result'] = {**saved, 'version': 2, 'raw': raw, 'dataset_id': dataset}
    stages = document['stages']
    raw = effective_raw(document)
    _, expected = identify(raw)
    invalid = legacy or (not saved) or ('3' in stages and stages['3'].get('dataset_id') != expected)
    if invalid:
        stale = {k:v for k,v in stages.items() if float(k) >= 3}
        if stale:
            document.setdefault('history', []).append({'revision':document.get('revision'), 'reason':'기준 로스백을 배경 전용으로 변경', 'stages':stale})
            for k in stale:del stages[k]


def geographic(e, n, origin):
    """Intersect the ENU vertical with the WGS84 ellipsoid (same basis as project)."""
    a, e2 = 6378137., 6.6943799901413165e-3
    lat, lon = map(math.radians, origin)
    N = a / math.sqrt(1-e2*math.sin(lat)**2)
    base = (N*math.cos(lat)*math.cos(lon), N*math.cos(lat)*math.sin(lon), N*(1-e2)*math.sin(lat))
    east = (-math.sin(lon), math.cos(lon), 0.)
    north = (-math.sin(lat)*math.cos(lon), -math.sin(lat)*math.sin(lon), math.cos(lat))
    up = (math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat))
    inv = (1/a**2, 1/a**2, 1/(a*a*(1-e2)))
    q = [base[i]+e*east[i]+n*north[i] for i in range(3)]
    A = sum(up[i]**2*inv[i] for i in range(3))
    B = 2*sum(q[i]*up[i]*inv[i] for i in range(3))
    C = sum(q[i]**2*inv[i] for i in range(3))-1
    discriminant = B*B-4*A*C
    if discriminant < 0 or B <= 0:
        raise web.HTTPBadRequest(text='현재 지도 범위 안에 구간을 배치하세요.')
    u = -2*C/(B+math.sqrt(discriminant))
    xyz = [q[i]+u*up[i] for i in range(3)]
    return math.degrees(math.atan2(xyz[2], math.hypot(xyz[0], xyz[1])*(1-e2))), math.degrees(math.atan2(xyz[1], xyz[0]))


def placement_result(source, clips):
    if not isinstance(clips, list) or len(clips) > 100:
        raise web.HTTPBadRequest(text='배치 구간은 최대 100개까지 저장할 수 있습니다.')
    raw = {**source['raw'], 'tracks': [], 'selected_bags': []}
    normalized, ids, total = [], set(), 0
    for item in clips:
        if not isinstance(item, dict):
            raise web.HTTPBadRequest(text='배치 구간 정보를 확인하세요.')
        key, bag, points = item.get('id'), item.get('bag'), item.get('points')
        start, end = item.get('start_seq'), item.get('end_seq')
        offsets = [item.get('offset_e'), item.get('offset_n')]
        angle = item.get('rotation_deg', 0.)
        if type(angle) not in (int, float) or not math.isfinite(angle):
            raise web.HTTPBadRequest(text='올바른 회전 각도를 입력하세요.')
        angle = math.fmod(angle, 360.)
        if angle > 180: angle -= 360
        if angle < -180: angle += 360
        if not isinstance(key, str) or not re.fullmatch(r'clip-[a-zA-Z0-9_-]{1,80}', key) or key in ids:
            raise web.HTTPBadRequest(text='배치 구간 ID가 잘못되었거나 중복되었습니다.')
        if not isinstance(bag, str) or not bag.strip() or len(bag) > 500:
            raise web.HTTPBadRequest(text='복사한 로스백 이름을 확인하세요.')
        if type(start) is not int or type(end) is not int or start < 1 or end <= start:
            raise web.HTTPBadRequest(text='같은 기록의 서로 다른 두 끝점을 선택하세요.')
        if not isinstance(points, list) or not 2 <= len(points) <= 100000 or len(points) != end-start+1:
            raise web.HTTPBadRequest(text='두 끝점을 포함한 연속 GPS 구간이 필요합니다.')
        total += len(points)
        if total > 100000:
            raise web.HTTPBadRequest(text='배치할 GPS는 최대 100,000점입니다.')
        if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v)>1000000 for v in offsets):
            raise web.HTTPBadRequest(text='배치 이동 거리를 확인하세요.')
        cleaned = []
        for seq, point in enumerate(points, start):
            if not isinstance(point, dict) or type(point.get('seq')) is not int or point['seq'] != seq:
                raise web.HTTPBadRequest(text='복사 구간의 원본 순번을 확인하세요.')
            lat, lon = point.get('lat'), point.get('lon')
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise web.HTTPBadRequest(text='올바른 GPS 위도·경도를 입력하세요.')
            cleaned.append({'seq': seq, 'lat': lat, 'lon': lon, 'break_before': point.get('break_before') is True and seq != start})
        projected = project(cleaned, raw['origin'])
        center_e = (min(p['e'] for p in projected)+max(p['e'] for p in projected))/2
        center_n = (min(p['n'] for p in projected)+max(p['n'] for p in projected))/2
        cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        placed = []
        for seq, point in enumerate(projected, 1):
            e, n = point['e']-center_e, point['n']-center_n
            moved_e, moved_n = (center_e+cosine*e-sine*n, center_n+sine*e+cosine*n) if angle else (point['e'], point['n'])
            lat, lon = geographic(moved_e+offsets[0], moved_n+offsets[1], raw['origin'])
            # A moved point cannot retain an original camera-location association.
            placed.append({'seq': seq, 'lat': lat, 'lon': lon, 'break_before': point['break_before'], 'source_seq': point['seq'], 'map_merge_clip': key})
        clip = {'id': key, 'bag': bag, 'start_seq': start, 'end_seq': end, 'points': cleaned, 'offset_e': offsets[0], 'offset_n': offsets[1], 'rotation_deg': angle}
        normalized.append(clip);ids.add(key)
        raw['tracks'].append({'name': f'{bag} · 복사 {start}~{end} ({key})', 'source_bag': bag, 'map_merge_clip': key, 'points': placed})
    _, dataset = identify(raw)
    return {'version': 2, 'source_dataset_id': source['dataset_id'], 'clips': normalized, 'raw': raw, 'dataset_id': dataset}
