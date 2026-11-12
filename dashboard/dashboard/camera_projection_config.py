"""Read the camera calibration referenced by main/config/path.jsonc."""
import os
from pathlib import Path

import json5
import yaml
from aiohttp import web


def camera_intrinsics():
    config_path = Path(os.environ.get(
        'DASHBOARD_PATH_CONFIG',
        Path(__file__).resolve().parents[2] / 'main/config/path.jsonc',
    ))
    try:
        paths = json5.loads(config_path.read_text(encoding='utf-8'))
        name = paths.get('camera_intrinsics_file') if isinstance(paths, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError('camera_intrinsics_file에 카메라 보정 파일 경로를 입력하세요.')
        path = Path(name)
        if not path.is_absolute():
            path = config_path.parent / path
        path = path.resolve()
        calibration = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(calibration, dict):
            raise ValueError('카메라 보정 파일은 YAML 객체여야 합니다.')
        if not all(key in calibration for key in ('image_width', 'image_height', 'camera_matrix', 'distortion_model', 'distortion_coefficients')):
            raise ValueError('카메라 보정 파일의 해상도·내부 행렬·왜곡 계수를 확인하세요.')
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise web.HTTPBadRequest(text=f'카메라 보정 설정을 읽을 수 없습니다: {error}')
    return {'path': str(path), 'calibration': calibration}


def projection_config():
    """Validated pinhole/distortion and vehicle mounting data for raw-frame overlays."""
    import math
    from .gps_path import vehicle_config
    result = camera_intrinsics()
    calibration = result['calibration']
    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)
    matrix = calibration.get('camera_matrix', {})
    coefficients = calibration.get('distortion_coefficients', {})
    if not isinstance(matrix, dict) or not isinstance(coefficients, dict):
        raise web.HTTPBadRequest(text='카메라 내부 행렬과 왜곡 계수 형식을 확인하세요.')
    k, d = matrix.get('data'), coefficients.get('data')
    if any(type(calibration.get(key)) is not int or calibration[key] <= 0 for key in ('image_width', 'image_height')):
        raise web.HTTPBadRequest(text='카메라 보정 해상도를 확인하세요.')
    if not isinstance(k, list) or len(k) != 9 or not all(map(finite, k)) or k[0] <= 0 or k[4] <= 0 or any(abs(k[i]) > 1e-9 for i in (1, 3, 6, 7)) or abs(k[8]-1) > 1e-9:
        raise web.HTTPBadRequest(text='지원하지 않는 카메라 내부 행렬입니다.')
    if calibration['distortion_model'] != 'plumb_bob' or not isinstance(d, list) or len(d) not in (4, 5) or not all(map(finite, d)):
        raise web.HTTPBadRequest(text='plumb_bob 4개 또는 5개 왜곡 계수만 지원합니다.')
    vehicle = vehicle_config()
    camera = vehicle.get('camera', {})
    if not isinstance(camera, dict) or any(not finite(camera.get(key)) for key in ('height_above_ground_m', 'distance_from_rear_m', 'lateral_offset_m', 'pitch_deg')) or camera['height_above_ground_m'] <= 0 or abs(camera['pitch_deg']) >= 90:
        raise web.HTTPBadRequest(text='vehicle.jsonc의 카메라 위치와 pitch_deg(-90~90도)를 확인하세요.')
    rear = vehicle.get('rear_axle_distance_from_rear_m')
    if not finite(rear):
        raise web.HTTPBadRequest(text='vehicle.jsonc의 후륜축 위치를 확인하세요.')
    return {**result, 'vehicle': {key: vehicle[key] for key in ('rear_axle_distance_from_rear_m', 'gps_antenna_offset_x_m', 'gps_antenna_offset_y_m')},
            'camera': camera, 'assumptions': {'ground': 'flat', 'heading': 'reference_path_tangent', 'camera_yaw_deg': 0, 'camera_roll_deg': 0}}
