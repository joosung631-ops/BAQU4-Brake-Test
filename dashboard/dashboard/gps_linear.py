"""The stage 8 waypoint polyline shared by stages 9 through final export."""
import math
import numpy as np
from aiohttp import web
from .gps_path import path_source, coordinates_to_gps
from .gps_review import digest

LINEAR_METHOD = 'ordered_waypoint_polyline_max_10cm_v1'
OUTPUT_SPACING_M = .1


def linear_source(document):
    saved = document['stages'].get('8')
    if not saved:
        raise web.HTTPConflict(text='먼저 8단계 웨이포인트를 저장하세요.')
    source = path_source(document)
    if saved.get('source_digest') != source['source_digest']:
        raise web.HTTPConflict(text='7단계 결과가 변경되었습니다. 8단계 웨이포인트를 다시 저장하세요.')
    vertices = []
    for p in source['points']:
        if vertices and p['segment_index'] != vertices[-1]['segment_index']:
            raise web.HTTPConflict(text='웨이포인트 사이에 기록 구간이 끊겨 있습니다. 8단계에서 연속된 경로로 정리하세요.')
        if not vertices or math.hypot(p['e']-vertices[-1]['e'], p['n']-vertices[-1]['n']) > 1e-8:
            vertices.append(p)
    if len(vertices) < 2:
        raise web.HTTPConflict(text='8단계에서 서로 다른 위치의 웨이포인트를 2개 이상 저장하세요.')
    points, station = [], 0.
    for a, b in zip(vertices, vertices[1:]):
        dx, dy = b['e']-a['e'], b['n']-a['n']
        length = math.hypot(dx, dy)
        heading = math.atan2(dy, dx)
        # Ignore sub-nanometre projection roundoff at exact 10cm multiples.
        count = max(1, math.ceil(length/OUTPUT_SPACING_M-1e-7))
        if len(points)+count+1 > 200000:
            raise web.HTTPBadRequest(text='직선 보간 출력은 최대 200,000점입니다. 웨이포인트 위치와 경로 길이를 확인하세요.')
        for i in range(count):
            distance = i*length/count
            points.append({'index':len(points)+1, 'e':a['e']+dx*distance/length,
                           'n':a['n']+dy*distance/length, 's_m':station+distance, 'heading_rad':heading})
        station += length
    points.append({'index':len(points)+1, 'e':vertices[-1]['e'], 'n':vertices[-1]['n'],
                   's_m':station, 'heading_rad':heading})
    ll = coordinates_to_gps(np.array([[p['e'],p['n']] for p in points]), source['origin'])
    for p, (lat, lon) in zip(points, ll):
        p.update(lat=float(lat), lon=float(lon))
    identity = {'method':LINEAR_METHOD, 'origin':source['origin'],
                'waypoints':[{k:p[k] for k in ('id','lat','lon','segment_index')} for p in source['points']]}
    return {'origin':source['origin'], 'points':points, 'source_digest':digest(identity),
            'method':LINEAR_METHOD, 'interpolation':'piecewise_linear', 'reference_point':'gps_antenna',
            'output_spacing_m':OUTPUT_SPACING_M, 'spacing_policy':'maximum_spacing_with_exact_waypoints',
            'waypoint_count':len(source['points']), 'statistics':{'point_count':len(points), 'length_m':station}}
