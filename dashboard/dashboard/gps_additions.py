"""User-added WGS84 points, scoped to a recording and ordered after an anchor."""
import copy
import math
import re
from aiohttp import web
from .gps_review import project, curve_segment


def addition_result(source, additions, source_digest):
    if not isinstance(additions, list) or len(additions) > 10000:
        raise web.HTTPBadRequest(text='추가할 GPS 포인트 목록을 확인하세요. 최대 10,000점입니다.')
    tracks = copy.deepcopy(source['tracks'])
    known = {t['id']: t for t in tracks}
    for track in tracks:
        track['points'] = [{**p, 'key': f"raw:{p['seq']}", 'source_seq': p['seq'], 'manual': False} for p in track['points']]
    ids = set()
    for item in additions:
        if not isinstance(item, dict):
            raise web.HTTPBadRequest(text='추가 포인트 형식을 확인하세요.')
        key, track_id, after = item.get('id'), item.get('track_id'), item.get('after')
        if not isinstance(key, str) or not re.fullmatch(r'manual-[a-zA-Z0-9_-]{1,80}', key) or key in ids:
            raise web.HTTPBadRequest(text='추가 포인트 ID가 잘못되었거나 중복되었습니다.')
        if not isinstance(track_id, str) or track_id not in known:
            raise web.HTTPBadRequest(text='포인트를 추가할 로스백을 선택하세요.')
        lat, lon = item.get('lat'), item.get('lon')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise web.HTTPBadRequest(text='올바른 위도(-90~90)와 경도(-180~180)를 입력하세요.')
        points = known[track_id]['points']
        index = -1 if after is None else next((i for i, p in enumerate(points) if p['key'] == after), None)
        if index is None:
            raise web.HTTPBadRequest(text='추가 위치의 기준점이 없습니다. 화면을 다시 불러오세요.')
        segment = points[index]['segment'] if index >= 0 else (points[0]['segment'] if points else 0)
        points.insert(index+1, {'key': key, 'lat': lat, 'lon': lon, 'segment': segment, 'manual': True, 'source_seq': None})
        ids.add(key)
    for track in tracks:
        if any(p['manual'] for p in track['points']):
            for index, point in enumerate(track['points'], 1):
                point['seq'] = index
    return {'source_digest': source_digest, 'additions': copy.deepcopy(additions), 'tracks': tracks}


def reference_tracks(tracks, origin, reviews):
    """Include added points in the reference curve used by order matching."""
    settings = {t['id']: t for t in reviews}
    result = []
    for track in tracks:
        segments, current, previous = [], [], None
        for point in project(track['points'], origin):
            if previous is not None and point['segment'] != previous:
                segments.append(curve_segment(current, settings.get(track['id'], {}).get('smoothing_m', .5)))
                current = []
            current.append(point)
            previous = point['segment']
        if current:
            segments.append(curve_segment(current, settings.get(track['id'], {}).get('smoothing_m', .5)))
        result.append({'id': track['id'], 'name': track['name'], 'curve_segments': segments, 'point_count': len(track['points'])})
    return result
