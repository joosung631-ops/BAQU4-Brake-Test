"""Estimated lane edges offset from the saved waypoint polyline."""
import math
import os
from pathlib import Path

import json5
from aiohttp import web
from .gps_review import digest
from .gps_linear import linear_source

CONFIG_PATH = 'main/config/road_conditions.jsonc'
LANE_METHOD = 'heading_normal_half_width_v1'


def road_config(require_width=True):
    path = Path(os.environ.get('DASHBOARD_ROAD_CONFIG', Path(__file__).resolve().parents[2] / CONFIG_PATH))
    try:
        config = json5.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise web.HTTPBadRequest(text=f'도로 설정 파일을 읽을 수 없습니다: {error}')
    if not isinstance(config, dict):
        raise web.HTTPBadRequest(text='도로 설정은 JSON 객체여야 합니다.')
    width = config.get('lane_width_m')
    if width is None and not require_width:
        return config
    if type(width) not in (int, float) or not math.isfinite(width) or width <= 0:
        raise web.HTTPBadRequest(text='main/config/road_conditions.jsonc의 lane_width_m에 0보다 큰 차선 폭(m)을 입력하세요.')
    return config


def lane_source(document):
    return linear_source(document)


def validate_lane_width(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise web.HTTPBadRequest(text='차선 폭은 0보다 큰 m 값으로 입력하세요.')
    return value


def lane_settings(document, config, width=None):
    source = lane_source(document)
    return {'method':LANE_METHOD, 'lane_width_m':validate_lane_width(config['lane_width_m'] if width is None else width),
            'road_config':config, 'road_digest':digest(config), 'road_config_path':CONFIG_PATH,
            'source_digest':source['source_digest'], 'reference_point':source['reference_point'], 'path_method':source['method']}


def lane_edges(points, width):
    half = width/2
    left, right = [], []
    for p in points:
        dx, dy = -math.sin(p['heading_rad'])*half, math.cos(p['heading_rad'])*half
        left.append({'e':p['e']+dx, 'n':p['n']+dy})
        right.append({'e':p['e']-dx, 'n':p['n']-dy})
    return {'left':left, 'right':right}


def vehicle_display_config():
    from .gps_path import vehicle_config
    config = vehicle_config()
    for key in ('vehicle_length_m', 'vehicle_width_m', 'rear_axle_distance_from_rear_m'):
        value = config.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (key != 'rear_axle_distance_from_rear_m' and value == 0):
            raise web.HTTPBadRequest(text=f'vehicle.jsonc의 {key} 값을 확인하세요.')
    if config['rear_axle_distance_from_rear_m'] > config['vehicle_length_m']:
        raise web.HTTPBadRequest(text='후륜축 위치가 차량 길이를 벗어납니다.')
    return {key:config[key] for key in ('vehicle_length_m','vehicle_width_m','rear_axle_distance_from_rear_m','gps_antenna_offset_x_m','gps_antenna_offset_y_m')}
