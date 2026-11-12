"""Task intervals bounded by cross-sections of the saved lane strip."""
import math
from aiohttp import web
from .gps_lane import lane_source, lane_edges
from .gps_review import digest


def section_source(project):
    source = lane_source(project)
    lane = project['stages'].get('9', {})
    if lane.get('source_digest') != source['source_digest'] or lane.get('enabled', True) is False or not lane.get('lane_width_m'):
        raise web.HTTPConflict(text='9단계에서 예상 차선을 적용하고 저장하세요.')
    return {**source, 'source_digest': digest(lane),
            'edges': lane_edges(source['points'], lane['lane_width_m']),
            'saved': project['stages'].get('10')}


def boundary(source, spec):
    if not isinstance(spec, dict):
        raise web.HTTPBadRequest(text='구간 시작·종료 선분을 선택하세요.')
    index, t = spec.get('segment_index'), spec.get('fraction')
    points = source['points']
    if type(index) is not int or not 0 <= index < len(points)-1 or type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t <= 1:
        raise web.HTTPBadRequest(text='구간 선분 위치가 경로 범위를 벗어났습니다.')
    def interpolate(items):
        a, b = items[index:index+2]
        return {k: a[k]+(b[k]-a[k])*t for k in ('e', 'n')}
    # s_m is the saved path station, with a geometric fallback for older maps.
    stations = source.get('_stations')
    if stations is None:
        stations = [0.]
        for a, b in zip(points, points[1:]):
            stations.append(stations[-1]+math.hypot(b['e']-a['e'], b['n']-a['n']))
        stations = [p.get('s_m', s) for p, s in zip(points, stations)]
        source['_stations'] = stations
    return {'segment_index': index, 'fraction': t,
            's_m': stations[index]+(stations[index+1]-stations[index])*t,
            'center': interpolate(points),
            'left': interpolate(source['edges']['left']), 'right': interpolate(source['edges']['right'])}


def section_result(project, specs):
    source = section_source(project)
    if not isinstance(specs, list):
        raise web.HTTPBadRequest(text='과제 구간 목록을 확인하세요.')
    result = []
    for spec in specs:
        if not isinstance(spec, dict):
            raise web.HTTPBadRequest(text='과제 구간 형식을 확인하세요.')
        name, description = spec.get('name'), spec.get('description')
        if not isinstance(name, str) or not name.strip() or not isinstance(description, str) or not description.strip():
            raise web.HTTPBadRequest(text='구간 이름과 설명을 입력하세요.')
        start, end = boundary(source, spec.get('start')), boundary(source, spec.get('end'))
        if result:
            start = result[-1]['end']
        if end['s_m'] <= start['s_m']+1e-6:
            raise web.HTTPBadRequest(text='구간 종료는 경로 진행 순서상 시작보다 뒤에 선택하세요.')
        result.append({'name': name.strip(), 'description': description.strip(), 'start': start, 'end': end})
    return {'source_digest': source['source_digest'], 'sections': result}
