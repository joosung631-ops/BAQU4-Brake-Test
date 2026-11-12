"""Display-only straight cone corridor, in original os_lidar coordinates.

No ROS, control commands, temporal accumulation, calibrated vehicle pose or
semantic stop guarantee. Deterministic pair consensus replaces random RANSAC:
at most 64 cone centres, then robust TLS refinement of parallel boundaries.
"""
from dataclasses import dataclass
from itertools import combinations
import math

import numpy as np


@dataclass(frozen=True)
class LineConfig:
    max_cones: int = 64
    side_tolerance_m: float = .22
    side_min_cones: int = 3
    side_min_span_m: float = 4.
    side_max_gap_m: float = 8.
    heading_limit_deg: float = 20.
    parallel_limit_deg: float = 6.
    width_min_m: float = 2.
    width_max_m: float = 8.
    origin_clearance_m: float = .8
    stop_tolerance_m: float = .28
    stop_min_cones: int = 3
    stop_interior_margin_m: float = .45
    stop_min_interior_cones: int = 2
    stop_span_fraction: float = .60
    stop_max_gap_m: float = 2.0
    stop_extension_m: float = 2.5


def _axes(theta):
    return np.array([math.cos(theta), math.sin(theta)]), np.array([-math.sin(theta), math.cos(theta)])


def _heading(points):
    q = points - points.mean(0)
    _, vectors = np.linalg.eigh(q.T @ q)
    t = vectors[:, -1]
    if t[0] < 0:
        t = -t
    return math.atan2(t[1], t[0])


def _side_candidates(p, cfg):
    if len(p) < cfg.side_min_cones:
        return []
    i, j = np.triu_indices(len(p), 1)
    d = p[j] - p[i]
    flip = d[:, 0] < 0
    d[flip] *= -1
    length = np.linalg.norm(d, axis=1)
    good = (length >= cfg.side_min_span_m) & (np.abs(np.arctan2(d[:, 1], d[:, 0])) <= math.radians(cfg.heading_limit_deg))
    d, i, length = d[good], i[good], length[good]
    if not len(i):
        return []
    normals = np.column_stack((-d[:, 1], d[:, 0])) / length[:, None]
    rho = np.einsum('ij,ij->i', normals, p[i])
    masks = np.abs(p @ normals.T - rho) <= cfg.side_tolerance_m
    support = masks.sum(0)
    # Bound refinement even in dense scenes. Unique supports prevent one side
    # from consuming the candidate quota with many identical seed pairs.
    order = np.argsort(-support, kind='stable')
    seen, candidates = set(), []
    for k in order:
        if support[k] < cfg.side_min_cones:
            break
        ids = np.flatnonzero(masks[:, k])
        key = tuple(ids)
        if key in seen:
            continue
        seen.add(key)
        theta = _heading(p[ids])
        if abs(theta) > math.radians(cfg.heading_limit_deg):
            continue
        t, n = _axes(theta)
        r = float(np.median(p[ids] @ n))
        ids = np.flatnonzero(np.abs(p @ n - r) <= cfg.side_tolerance_m)
        station = p[ids] @ t
        # A far collinear object cannot bridge an unobserved long gap.
        ids = ids[np.argsort(station)]
        cuts = np.flatnonzero(np.diff(p[ids] @ t) > cfg.side_max_gap_m) + 1
        for segment in np.split(ids, cuts):
            if len(segment) < cfg.side_min_cones:
                continue
            s = p[segment] @ t
            span = float(np.ptp(s))
            if span < cfg.side_min_span_m:
                continue
            residual = p[segment] @ n - r
            rmse = float(np.sqrt(np.mean(residual ** 2)))
            score = float(np.sum(1 / (1 + np.maximum(0, s) / 20)) + .06 * min(span, 30) - 2 * rmse)
            candidates.append(dict(ids=segment, theta=theta, rho=r, score=score))
        if len(seen) >= 96:
            break
    candidates.sort(key=lambda c: -c['score'])
    result, seen = [], set()
    for c in candidates:
        key = tuple(sorted(c['ids']))
        if key not in seen:
            result.append(c)
            seen.add(key)
    return result[:24]


def _parallel_pair(p, a, b, cfg):
    if abs(a['theta'] - b['theta']) > math.radians(cfg.parallel_limit_deg):
        return None
    groups = [p[a['ids']], p[b['ids']]]
    # Common tangent from within-row covariance, not from covariance across
    # rows (which would confuse road width with heading).
    covariance = sum((g - g.mean(0)).T @ (g - g.mean(0)) for g in groups)
    _, vectors = np.linalg.eigh(covariance)
    tangent = vectors[:, -1]
    if tangent[0] < 0:
        tangent = -tangent
    theta = math.atan2(tangent[1], tangent[0])
    t, n = _axes(theta)
    rows = []
    for g in groups:
        r = float(np.median(g @ n))
        ids = np.flatnonzero(np.abs(p @ n - r) <= cfg.side_tolerance_m)
        s = p[ids] @ t
        # Preserve each original connected observation interval.
        original_s = g @ t
        ids = ids[(s >= original_s.min() - .3) & (s <= original_s.max() + .3)]
        if len(ids) < cfg.side_min_cones or np.ptp(p[ids] @ t) < cfg.side_min_span_m:
            return None
        s = np.sort(p[ids] @ t)
        if np.max(np.diff(s)) > cfg.side_max_gap_m:
            return None
        rows.append(dict(ids=ids, rho=r, start=float(s.min()), end=float(s.max()),
                         rmse=float(np.sqrt(np.mean((p[ids] @ n - r) ** 2)))))
    left, right = sorted(rows, key=lambda r: -r['rho'])
    width = left['rho'] - right['rho']
    overlap = min(left['end'], right['end']) - max(left['start'], right['start'])
    if (not cfg.width_min_m <= width <= cfg.width_max_m or
            left['rho'] < cfg.origin_clearance_m or right['rho'] > -cfg.origin_clearance_m or
            overlap < cfg.side_min_span_m or max(left['rmse'], right['rmse']) > cfg.side_tolerance_m):
        return None
    return dict(t=t, n=n, left=left, right=right, width=width,
                score=a['score'] + b['score'], theta=theta)


def _stop_row(p, pair, cfg):
    t, n = pair['t'], pair['n']
    s, q = p @ t, p @ n
    low, high = pair['right']['rho'], pair['left']['rho']
    width = high - low
    eligible = np.flatnonzero((q >= low - .3) & (q <= high + .3) &
                              (s >= .8) & (s <= min(pair['left']['end'], pair['right']['end']) + cfg.stop_extension_m))
    found, seen = [], set()
    for i, j in combinations(eligible, 2):
        if abs(q[j] - q[i]) < width * .4:
            continue
        slope = (s[j] - s[i]) / (q[j] - q[i])
        if abs(slope) > math.tan(math.radians(cfg.heading_limit_deg)):
            continue
        intercept = s[i] - slope * q[i]
        ids = eligible[np.abs(s[eligible] - slope * q[eligible] - intercept) / math.hypot(1, slope) <= cfg.stop_tolerance_m]
        key = tuple(ids)
        if key in seen or len(ids) < cfg.stop_min_cones:
            continue
        seen.add(key)
        # At least two cones strictly inside the corridor: the normal pair of
        # left/right boundary cones at the same station is never a stop row.
        interior = (q[ids] > low + cfg.stop_interior_margin_m) & (q[ids] < high - cfg.stop_interior_margin_m)
        lateral = np.sort(q[ids])
        if (interior.sum() < cfg.stop_min_interior_cones or np.ptp(lateral) < width * cfg.stop_span_fraction or
                lateral[0] - low > max(.65, .2 * width) or high - lateral[-1] > max(.65, .2 * width) or
                np.max(np.diff(lateral)) > cfg.stop_max_gap_m):
            continue
        slope, intercept = np.linalg.lstsq(np.column_stack((q[ids], np.ones(len(ids)))), s[ids], rcond=None)[0]
        if abs(slope) > math.tan(math.radians(cfg.heading_limit_deg)):
            continue
        rmse = float(np.sqrt(np.mean((s[ids] - slope * q[ids] - intercept) ** 2)) / math.hypot(1, slope))
        if rmse > cfg.stop_tolerance_m:
            continue
        mid = (high + low) / 2
        distance = float(slope * mid + intercept)
        found.append(dict(ids=ids, slope=float(slope), intercept=float(intercept), distance=distance,
                          low=float(lateral[0]), high=float(lateral[-1]), rmse=rmse))
    return min(found, key=lambda r: (r['distance'], -len(r['ids']))) if found else None


def extract_course_lines(centers, plane, config=None):
    """Return bounded display geometry; absent evidence produces absent lines.

    Endpoints are in cm in raw sensor axes, lifted 8 cm above this scan's ground
    plane solely for visibility. 'center' is an inferred reference, 'stop' is
    always a geometric candidate, never a command or confirmed obstacle.
    """
    cfg = config or LineConfig()
    result = dict(state='none', reason='insufficient_cones', frame='os_lidar', lines={}, stop_state='none')
    raw = np.asarray(centers, dtype=float)
    plane = np.asarray(plane, dtype=float)
    if raw.size == 0:
        return result
    if raw.ndim != 2 or raw.shape[1] != 3 or not np.isfinite(raw).all() or plane.shape != (3,) or not np.isfinite(plane).all():
        raise ValueError('Invalid cone centres or ground plane')
    raw = raw[np.argsort(np.linalg.norm(raw[:, :2], axis=1), kind='stable')[:cfg.max_cones]]
    # Nominal forward/left only, explicitly NOT a calibrated base_link transform.
    p = -raw[:, :2]
    candidates = _side_candidates(p, cfg)

    def line(points, count, rmse):
        xy = -np.asarray(points)
        z = xy @ plane[:2] + plane[2] + .08
        xyz = np.column_stack((xy, z))
        return dict(points_cm=np.rint(xyz * 100).astype(int).ravel().tolist(),
                    cones=int(count), rmse_cm=round(float(rmse) * 100, 1))

    pairs = [v for a, b in combinations(candidates, 2) if (v := _parallel_pair(p, a, b, cfg)) is not None]
    pairs.sort(key=lambda c: -c['score'])
    if not pairs:
        # Display at most one measured row per side; never invent the missing
        # boundary/road width to manufacture a center or transverse stop row.
        for name, sign in (('left', 1), ('right', -1)):
            c = next((c for c in candidates if sign * c['rho'] >= cfg.origin_clearance_m), None)
            if c is None:
                continue
            t, n = _axes(c['theta'])
            s = p[c['ids']] @ t
            result['lines'][name] = line([t * s.min() + n * c['rho'], t * s.max() + n * c['rho']], len(s),
                                         np.sqrt(np.mean((p[c['ids']] @ n - c['rho']) ** 2)))
        if result['lines']:
            result.update(state='partial', reason='no_parallel_pair')
        return result
    pair = pairs[0]
    # Competing nearly-equal corridors of materially different width are not
    # resolved by claiming that the strongest-looking one must be the track.
    ambiguous = any(v['score'] >= pair['score'] * .92 and abs(v['width'] - pair['width']) > .8 for v in pairs[1:])
    t, n = pair['t'], pair['n']
    stop = None if ambiguous else _stop_row(p, pair, cfg)
    middle = (pair['left']['rho'] + pair['right']['rho']) / 2
    stop_station = stop['distance'] if stop else math.inf
    for name in ('left', 'right'):
        row = pair[name]
        # Intersect with a slanted stop candidate at this boundary, rather
        # than cutting both sides at the same longitudinal coordinate.
        end = min(row['end'], stop['slope'] * row['rho'] + stop['intercept']) if stop else row['end']
        if end > row['start']:
            result['lines'][name] = line([t * row['start'] + n * row['rho'], t * end + n * row['rho']], len(row['ids']), row['rmse'])
    result.update(state='ambiguous' if ambiguous else 'paired', reason='competing_corridors' if ambiguous else 'parallel_consensus',
                  width_cm=round(pair['width'] * 100), heading_deg=round(math.degrees(pair['theta']), 1))
    if not ambiguous:
        start = max(pair['left']['start'], pair['right']['start'])
        end = min(pair['left']['end'], pair['right']['end'], stop_station)
        if end > start:
            result['lines']['center'] = line([t * start + n * middle, t * end + n * middle],
                                              len(pair['left']['ids']) + len(pair['right']['ids']), max(pair['left']['rmse'], pair['right']['rmse']))
        if stop:
            q = np.array([stop['low'], stop['high']])
            points = (stop['slope'] * q + stop['intercept'])[:, None] * t + q[:, None] * n
            result['lines']['stop'] = line(points, len(stop['ids']), stop['rmse'])
            result.update(stop_state='candidate', stop_distance_cm=round(stop_station * 100))
    return result
