"""Export the final path and lane boundaries without editing history."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from aiohttp import web
from .gps_final_points import apply_final_points
from .gps_sections import section_result
from .gps_review import digest
from .gps_lane import lane_source, lane_edges


def user_suffix(name):
    return re.sub(r'^(?:(?:\d+단계|맵|MAP)_\d{4}-\d{2}-\d{2}_\d{6,12}_)', '', name[:-5])


def final_map(project):
    source = lane_source(project)
    lane = project['stages'].get('9')
    if not lane or lane.get('source_digest') != source['source_digest']:
        raise web.HTTPConflict(text='먼저 9단계 예상 차선 적용 결과를 저장하세요.')
    saved_sections = project['stages'].get('10')
    sections = []
    if saved_sections:
        if saved_sections.get('source_digest') != digest(lane):
            raise web.HTTPConflict(text='10단계 과제 구간을 다시 저장하세요.')
        sections = section_result(project, saved_sections['sections'])['sections']
    keys = ('index','s_m','e','n','lat','lon','heading_rad','curvature_per_m','steering_deg')
    points = [{key:p[key] for key in keys if key in p} for p in source['points']]
    points, sections = apply_final_points(project, points, sections)
    enabled = lane.get('enabled', True)
    return {'format':'gps-final-map','version':1,'created_at':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
            'coordinate_system':{'geographic':'WGS84','local':'ENU','origin':source['origin'],
                                 'distance_unit':'m','heading':'radians counterclockwise from east'},
            'reference_point':source['reference_point'],'closed':False,
            'path_method':source['method'],'interpolation':source['interpolation'],'spacing_policy':('explicit_final_waypoint_insertions' if project['stages'].get('10.5',{}).get('additions') else source['spacing_policy']),
            'output_spacing_m':(None if project['stages'].get('10.5',{}).get('additions') else source['output_spacing_m']),
            'task_sections':sections,'points':points,'lanes':{'enabled':enabled,'width_m':lane['lane_width_m'] if enabled else None,
                                   'boundaries':lane_edges(points,lane['lane_width_m']) if enabled else None}}
