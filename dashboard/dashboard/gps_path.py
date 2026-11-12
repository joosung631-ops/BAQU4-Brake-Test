"""Open rear-axle paths fitted to ordered GNSS with steering constraints."""
import math
import os
import time
import re
from pathlib import Path

import json5
import numpy as np
from aiohttp import web
from scipy.interpolate import BSpline, PPoly
from scipy.optimize import minimize
from scipy.integrate import cumulative_simpson

from .gps_review import project, digest

CONFIG_PATH = 'main/config/vehicle.jsonc'
PATH_METHOD = 'cubic_bspline_constrained_rear_axle_gnss_lever_arm_v2'



def single_path_result(result):
    """Lossless conversion of the legacy one-segment stage 8 storage."""
    if 'segments' not in result:
        return result
    segments = result['segments']
    if len(segments) != 1:
        raise web.HTTPConflict(text='이전 8단계 결과가 여러 구간입니다. 7단계에서 하나의 연속 경로로 정리한 뒤 다시 생성하세요.')
    segment = segments[0]
    points = result['points']
    if len(points) != len(segment['samples']) or any(
        any(point.get(key) != value for key, value in sample.items())
        for point, sample in zip(points, segment['samples'])
    ):
        raise web.HTTPConflict(text='기존 8단계 중복 좌표가 서로 일치하지 않습니다. 파일을 확인하세요.')
    return {**{k:v for k,v in result.items() if k not in ('segments','points')},
            'format_version':2,
            'points':[{k:v for k,v in point.items() if k not in ('segment_index','break_before')} for point in points],
            **{key:segment[key] for key in ('matches','spline','validation','violations')}}


def vehicle_config():
    path = Path(os.environ.get('DASHBOARD_VEHICLE_CONFIG', Path(__file__).resolve().parents[2] / CONFIG_PATH))
    try:
        data = json5.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise web.HTTPBadRequest(text=f'차량 설정 파일을 읽을 수 없습니다: {exc}')
    limits = {'wheelbase_m': (0, 20), 'max_front_steering_left_deg': (0, 89),
              'max_front_steering_right_deg': (0, 89)}
    for key, (low, high) in limits.items():
        v = data.get(key)
        if type(v) not in (int, float) or not math.isfinite(v) or not low < v <= high:
            raise web.HTTPBadRequest(text=f'차량 설정 {key} 값을 확인하세요.')
    for key in ('gps_antenna_offset_x_m', 'gps_antenna_offset_y_m', 'path_reference_offset_x_m', 'path_reference_offset_y_m'):
        v = data.get(key)
        if type(v) not in (int, float) or not math.isfinite(v):
            raise web.HTTPBadRequest(text=f'차량 설정 {key} 값을 입력하세요.')
    if data['path_reference_offset_x_m'] != 0 or data['path_reference_offset_y_m'] != 0:
        raise web.HTTPBadRequest(text='8단계 경로 기준점은 후륜축 중앙입니다. path_reference_offset_x_m/y_m을 0으로 설정하세요.')
    return data


def waypoint_payload(points):
    return [({'id':p['id'], 'lat':p['lat'], 'lon':p['lon'], 'segment_index':p['segment_index']} if p['manual'] else {'id':p['id']}) for p in points]


def path_source(document, waypoints=None):
    stages = document['stages']
    if '7' not in stages:
        raise web.HTTPConflict(text='먼저 7단계 순서 매칭을 저장하세요.')
    points = project(stages['7']['ordered_points'], stages['2']['raw']['origin'])
    for p in points:
        p['segment_index'] = stages['7']['matches'][p['point_index']]['segment_index']
        p.update(id=f"source-{p['index']}", source_index=p['index'], manual=False)
    segment_indexes = sorted({p['segment_index'] for p in points}) or [0]
    source_digest = digest(stages['7'])
    if waypoints is None:
        saved = stages.get('8', {})
        if saved.get('source_digest') == source_digest:
            waypoints = saved.get('waypoints')
    if waypoints is not None:
        if not isinstance(waypoints, list) or len(waypoints) > 100000:
            raise web.HTTPBadRequest(text='웨이포인트 목록을 확인하세요. 최대 100,000점입니다.')
        known = {p['id']:p for p in points}
        segments = {p['segment_index'] for p in points} or {0}
        output, seen = [], set()
        for spec in waypoints:
            if not isinstance(spec, dict) or not isinstance(spec.get('id'), str) or spec['id'] in seen:
                raise web.HTTPBadRequest(text='웨이포인트 ID가 잘못되었거나 중복되었습니다.')
            key = spec['id']
            if key in known:
                point = {**known[key]}
            else:
                lat, lon, segment = spec.get('lat'), spec.get('lon'), spec.get('segment_index')
                if not re.fullmatch(r'manual-[a-zA-Z0-9_-]{1,80}', key):
                    raise web.HTTPBadRequest(text='원본에 없는 웨이포인트입니다. 화면을 다시 불러오세요.')
                if any(type(v) not in (int,float) or not math.isfinite(v) for v in (lat,lon)) or not -90<=lat<=90 or not -180<=lon<=180:
                    raise web.HTTPBadRequest(text='추가할 웨이포인트의 위도·경도를 확인하세요.')
                if type(segment) is not int or segment not in segments:
                    raise web.HTTPBadRequest(text='웨이포인트의 기록 구간을 확인하세요.')
                point = project([{'id':key,'lat':lat,'lon':lon,'segment_index':segment,'source_index':None,'manual':True}], stages['2']['raw']['origin'])[0]
            output.append({**point,'index':len(output)+1})
            seen.add(key)
        points = output
    return {'points': points, 'waypoints':waypoint_payload(points), 'origin': stages['2']['raw']['origin'], 'source_digest': source_digest, 'segment_indexes': segment_indexes}


def path_settings(settings):
    if not isinstance(settings, dict):
        raise web.HTTPBadRequest(text='경로 설정이 필요합니다.')
    for key, low, high in [('max_deviation_m', .001, 5.), ('smoothing', 0., 100.)]:
        v = settings.get(key)
        if type(v) not in (int,float) or not math.isfinite(v) or not low<=v<=high:
            raise web.HTTPBadRequest(text=f'{key}: {low}~{high} 사이 숫자를 입력하세요.')
    return {key:settings[key] for key in ('max_deviation_m','smoothing')}


def coordinates_to_gps(xy, origin):
    """Inverse of gps_review.project on the WGS84 zero-altitude ellipsoid."""
    lat, lon = np.radians(origin)
    a, e2 = 6378137., 6.6943799901413165e-3
    n = a / np.sqrt(1-e2*np.sin(lat)**2)
    base = np.array([n*np.cos(lat)*np.cos(lon), n*np.cos(lat)*np.sin(lon), n*(1-e2)*np.sin(lat)])
    east = np.array([-np.sin(lon), np.cos(lon), 0])
    north = np.array([-np.sin(lat)*np.cos(lon), -np.sin(lat)*np.sin(lon), np.cos(lat)])
    up = np.array([np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)])
    q = base + xy[:, :1]*east + xy[:, 1:]*north
    inv = np.array([1/a**2, 1/a**2, 1/(a*a*(1-e2))])
    aa = np.sum(up*up*inv); bb = 2*np.sum(q*up*inv, axis=1); cc = np.sum(q*q*inv, axis=1)-1
    u = -2*cc/(bb+np.sqrt(np.maximum(0, bb*bb-4*aa*cc)))
    q += u[:, None]*up
    return np.column_stack((np.degrees(np.arctan2(q[:, 2], np.hypot(q[:, 0], q[:, 1])*(1-e2))), np.degrees(np.arctan2(q[:, 1], q[:, 0]))))


class Curve:
    def __init__(self, knots, u, offset):
        self.knots = knots
        self.b = [BSpline(knots, np.eye(len(knots)-4), 3)(u, nu=i) for i in range(3)]
        self.offset = offset

    def evaluate(self, z, jac=False):
        b, d, dd = self.b
        controls = z.reshape(2, -1).T
        r, v, acc = b @ controls, d @ controls, dd @ controls
        speed = np.maximum(np.linalg.norm(v, axis=1), 1e-9)
        t = v/speed[:, None]
        a, lateral = self.offset
        q = r + a*t + lateral*np.column_stack((-t[:, 1], t[:, 0]))
        k = (v[:, 0]*acc[:, 1]-v[:, 1]*acc[:, 0])/speed**3
        if not jac:
            return r, q, k, speed, np.arctan2(v[:, 1], v[:, 0])
        tx, ty = t.T
        jxx = (1-tx*tx)/speed; jxy = -tx*ty/speed; jyy = (1-ty*ty)/speed
        qx = np.hstack((b+(a*jxx-lateral*jxy)[:, None]*d, (a*jxy-lateral*jyy)[:, None]*d))
        qy = np.hstack(((a*jxy+lateral*jxx)[:, None]*d, b+(a*jyy+lateral*jxy)[:, None]*d))
        kx = (acc[:, 1, None]*d-v[:, 1, None]*dd)/speed[:, None]**3 - (3*k*v[:, 0]/speed**2)[:, None]*d
        ky = (v[:, 0, None]*dd-acc[:, 0, None]*d)/speed[:, None]**3 - (3*k*v[:, 1]/speed**2)[:, None]*d
        jspeed = np.hstack((tx[:, None]*d, ty[:, None]*d))
        return r, q, k, speed, np.arctan2(v[:, 1], v[:, 0]), qx, qy, np.hstack((kx, ky)), jspeed



def curvature_extrema(knots, z):
    """Check interior curvature/speed extrema as well as evenly spaced samples."""
    from numpy.polynomial import Polynomial
    controls = z.reshape(2, -1)
    polys = [PPoly.from_spline(BSpline(knots, axis, 3)) for axis in controls]
    candidates = list(np.unique(knots))
    for i, (start, end) in enumerate(zip(polys[0].x, polys[0].x[1:])):
        if end <= start:
            continue
        x, y = [Polynomial(poly.c[:, i][::-1]) for poly in polys]
        dx, dy = x.deriv(), y.deriv()
        speed2 = dx*dx+dy*dy
        cross = dx*dy.deriv()-dy*dx.deriv()
        numerator = cross.deriv()*speed2-1.5*cross*speed2.deriv()
        for equation in (numerator, speed2.deriv()):
            for root in equation.roots():
                if abs(root.imag)<1e-8 and 0<root.real<end-start:
                    candidates.append(start+float(root.real))
    return np.array(candidates)


def fit_segment(points, vehicle, settings, origin, deadline):
    positions = np.array([[p['e'], p['n']] for p in points])
    anchor = positions[0].copy(); positions -= anchor
    original_u = np.r_[0., np.cumsum(np.linalg.norm(np.diff(positions, axis=0), axis=1))]
    keep = np.r_[True, np.diff(original_u) > 1e-6]
    u, p = original_u[keep], positions[keep]
    if len(u) < 2:
        raise web.HTTPBadRequest(text='서로 다른 위치의 GPS 점이 2개 이상 필요합니다.')
    length = u[-1]
    if length > 10000:
        raise web.HTTPBadRequest(text='한 구간은 10km 이내로 나누어 계산하세요.')
    count = min(180, max(4, min(len(u), int(math.ceil(length/3))+3)))
    # Do not give sparse GPS more control points than observations (except cubic minimum).
    knots = np.r_[np.zeros(4), np.linspace(0, length, count-2)[1:-1], np.full(4, length)]
    offset = (vehicle['gps_antenna_offset_x_m'], vehicle['gps_antenna_offset_y_m'])
    initial = Curve(knots, u, offset)
    # Few GPS samples may leave controls unconstrained; initialize with dense linear samples.
    iu = np.linspace(0, length, max(30, count*3)); ip = np.column_stack([np.interp(iu, u, p[:, j]) for j in (0, 1)])
    idir = np.gradient(ip, iu, axis=0); idir /= np.linalg.norm(idir, axis=1)[:, None].clip(1e-9)
    ir = ip-offset[0]*idir-offset[1]*np.column_stack((-idir[:, 1], idir[:, 0]))
    z = np.linalg.lstsq(Curve(knots, iu, offset).b[0], ir, rcond=None)[0].T.ravel()
    left = math.tan(math.radians(vehicle['max_front_steering_left_deg']))/vehicle['wheelbase_m']
    right = math.tan(math.radians(vehicle['max_front_steering_right_deg']))/vehicle['wheelbase_m']
    tolerance = settings['max_deviation_m']; strength = settings['smoothing']
    grid = np.unique(np.r_[u, np.linspace(0, length, max(3, math.ceil(length/.5)+1))])
    # Weight physical distance, so dense samples and stop clusters do not dominate.
    weight = np.r_[np.diff(u)[0]/2, (u[2:]-u[:-2])/2, np.diff(u)[-1]/2] if len(u)>2 else np.ones(2)
    weight /= weight.sum()
    status = '계산 전'; iterations = 0; converged = False
    last = z.copy()
    def callback(x):
        nonlocal last
        last = x.copy()
        if time.monotonic() > deadline:
            raise TimeoutError()
    for refinement in range(4):
        sample = Curve(knots, grid, offset)
        endpoint = Curve(knots, [0, length], offset)
        # Fixed physical-distance quadrature keeps smoothing independent of constraint refinement.
        fair_u = np.linspace(0, length, max(3, math.ceil(length/.25)+1))
        fair_h = length/(len(fair_u)-1)
        fair_w = np.full(len(fair_u), fair_h/length); fair_w[[0,-1]] *= .5
        basis = BSpline(knots, np.eye(len(knots)-4), 3)
        second, third = basis(fair_u, nu=2), basis(fair_u, nu=3)
        fairness = (0.5+2*strength)*(second.T @ (fair_w[:,None]*second))
        fairness += (1+8*strength)*(third.T @ (fair_w[:,None]*third))
        def objective(x):
            _, q, _, _, _, qx, qy, _, _ = initial.evaluate(x, True)
            error = q-p
            controls = x.reshape(2,-1)
            fair_grad = controls @ fairness
            value = np.sum(weight*np.sum(error**2, axis=1)) + np.sum(controls*fair_grad)
            grad = 2*(qx.T@(weight*error[:, 0])+qy.T@(weight*error[:, 1]))
            grad += 2*fair_grad.ravel()
            return value, grad
        def inequalities(x):
            _, q, k, speed, _, qx, qy, jk, js = sample.evaluate(x, True)
            _, pq, _, _, _, px, py, _, _ = initial.evaluate(x, True)
            err = pq-p
            value = np.r_[left-k, right+k, tolerance*tolerance-np.sum(err*err, axis=1), speed-.05]
            jac = np.vstack((-jk, jk, -2*(err[:, :1]*px+err[:, 1:]*py), js))
            return value, jac
        def ends(x):
            _, q, _, _, _, qx, qy, _, _ = endpoint.evaluate(x, True)
            return (q-p[[0, -1]]).T.ravel(), np.vstack((qx, qy))
        try:
            opt = minimize(objective, z, jac=True, method='SLSQP',
                constraints=[{'type':'ineq','fun':lambda x:inequalities(x)[0],'jac':lambda x:inequalities(x)[1]},
                             {'type':'eq','fun':lambda x:ends(x)[0],'jac':lambda x:ends(x)[1]}],
                callback=callback, options={'maxiter':250, 'ftol':1e-9})
            z = opt.x; status = str(opt.message); iterations += int(opt.nit); converged = bool(opt.success)
        except TimeoutError:
            z = last; status = '계산 시간 제한에 도달했습니다.'; break
        check_u = np.unique(np.r_[u, curvature_extrema(knots, z), np.linspace(0, length, max(3, math.ceil(length/.02)+1))])
        _, q, k, speed, _ = Curve(knots, check_u, offset).evaluate(z)
        bad = (k>left+1e-5)|(k < -right-1e-5)|(speed<.0499)
        if not bad.any():
            break
        grid = np.unique(np.r_[grid, check_u[bad][::max(1, np.count_nonzero(bad)//400)]])
    # Validate more densely than the 10 cm exported samples, independently of solver success.
    check_u = np.unique(np.r_[u, curvature_extrema(knots, z), np.linspace(0, length, max(3, math.ceil(length/.02)+1))])
    dense = Curve(knots, check_u, offset)
    r, q, k, speed, yaw = dense.evaluate(z)
    if not all(np.isfinite(a).all() for a in (r, q, k, speed)):
        raise web.HTTPBadRequest(text='수치적으로 안정된 경로를 만들지 못했습니다. 순서와 설정을 확인하세요.')
    _, prediction, point_k, _, _ = Curve(knots, original_u, offset).evaluate(z)
    residual = np.linalg.norm(prediction-positions, axis=1)
    excess = (k>left+1e-5)|(k < -right-1e-5)|(speed<.0499)
    point_excess = residual>tolerance+1e-4
    endpoint_error = float(max(np.linalg.norm(q[0]-p[0]), np.linalg.norm(q[-1]-p[-1])))
    valid = not excess.any() and not point_excess.any() and endpoint_error<=1e-4 and status!='계산 시간 제한에 도달했습니다.'
    arclength = np.r_[0., cumulative_simpson(speed, x=check_u)]
    distances = np.r_[np.arange(0, arclength[-1], .1), arclength[-1]]
    if len(distances)>1 and distances[-1]-distances[-2]<1e-7:
        distances = distances[:-1]; distances[-1] = arclength[-1]
    out_u = np.interp(distances, arclength, check_u)
    rr, qq, kk, _, yy = Curve(knots, out_u, offset).evaluate(z)
    ll = coordinates_to_gps(rr+anchor, origin)
    samples = [{'s_m':float(s), 'e':float(pos[0]+anchor[0]), 'n':float(pos[1]+anchor[1]),
                'lat':float(gps[0]),'lon':float(gps[1]),'heading_rad':float(angle),'curvature_per_m':float(curvature),
                'steering_deg':float(np.degrees(np.arctan(vehicle['wheelbase_m']*curvature))),
                'gps_e':float(pred[0]+anchor[0]),'gps_n':float(pred[1]+anchor[1])}
               for s,pos,gps,angle,curvature,pred in zip(distances,rr,ll,yy,kk,qq)]
    matches = [{'index':point['index'],'distance_m':float(err),'gps_e':float(pred[0]+anchor[0]),'gps_n':float(pred[1]+anchor[1]),
                'steering_deg':float(np.degrees(np.arctan(vehicle['wheelbase_m']*curvature)))}
               for point,err,pred,curvature in zip(points,residual,prediction,point_k)]
    violations = [{'e':float(r[i,0]+anchor[0]),'n':float(r[i,1]+anchor[1]),'distance_m':None,
                   'steering_deg':float(np.degrees(np.arctan(vehicle['wheelbase_m']*k[i])))} for i in np.flatnonzero(excess)[::max(1,np.count_nonzero(excess)//1000)]]
    for i in np.flatnonzero(point_excess):
        violations.append({'e':float(prediction[i,0]+anchor[0]),'n':float(prediction[i,1]+anchor[1]),'distance_m':float(residual[i]),
                           'steering_deg':float(np.degrees(np.arctan(vehicle['wheelbase_m']*point_k[i])))})
    return {'valid':bool(valid),'points':samples,'matches':matches,'violations':violations,
            'spline':{'degree':3,'knots':knots.tolist(),'controls_en':(z.reshape(2,-1).T+anchor).tolist()},
            'validation':{'max_deviation_m':float(residual.max()),'endpoint_error_m':endpoint_error,
                          'max_abs_steering_deg':float(np.degrees(np.arctan(vehicle['wheelbase_m']*np.abs(k).max()))),
                          'violation_samples':int(excess.sum()+point_excess.sum()),'parameter_check_step_m':.02,'includes_curvature_extrema':True,
                          'distance_tolerance_m':1e-4,'curvature_tolerance_per_m':1e-5,
                          'solver_message':status,'solver_converged':converged,'iterations':iterations}}


def generate_path(document, vehicle, settings, waypoints=None):
    settings = path_settings(settings)
    source = path_source(document, waypoints)
    if len(source['points'])<2:
        raise web.HTTPBadRequest(text='경로를 생성할 웨이포인트가 2개 이상 필요합니다.')
    points = source['points']
    for previous, current in zip(points, points[1:]):
        if previous['segment_index'] != current['segment_index']:
            raise web.HTTPBadRequest(text=f"순서 #{previous['index']}와 #{current['index']} 사이에 기록 구간이 끊겨 있습니다. 7단계에서 하나의 연속 경로로 정리하세요.")
    fitted = fit_segment(points,vehicle,settings,source['origin'],time.monotonic()+120)
    distances = np.array([m['distance_m'] for m in fitted['matches']])
    samples = [{**point,'index':i} for i,point in enumerate(fitted['points'],1)]
    return {**fitted,'format_version':2,'settings':{**settings,'closed':False,'output_spacing_m':.1},
            'reference_point':'rear_axle_center','vehicle_config':vehicle,'vehicle_digest':digest(vehicle),
            'vehicle_config_path':CONFIG_PATH,'source_digest':source['source_digest'],'origin':source['origin'],
            'method':PATH_METHOD,'points':samples,'waypoints':source['waypoints'],'waypoints_digest':digest(source['waypoints']),
            'statistics':{'distance_min_m':float(distances.min()),'distance_max_m':float(distances.max()),
                          'distance_mean_m':float(distances.mean()),'distance_std_m':float(distances.std()),
                          'length_m':samples[-1]['s_m'],'point_count':len(samples),
                          'max_abs_steering_deg':fitted['validation']['max_abs_steering_deg'],
                          'violation_samples':fitted['validation']['violation_samples']}}
