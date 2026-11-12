"""Sparse transverse occupancy for the closed, straight brake-test course.

This is display evidence, not cone classification or a brake decision. All
endpoints stay in os_lidar axes. A verified near road plane cannot prove the
far road is planar; slopes and other obstacles remain outside the assumption.
"""
from collections import deque
from dataclasses import dataclass
import math

import numpy as np

from .detector import heights_above_plane


@dataclass(frozen=True)
class StopRowConfig:
    range_min_m: float = 2.
    range_max_m: float = 45.
    min_height_m: float = .15
    max_height_m: float = 1.05
    cell_m: float = .35
    depth_m: float = .60
    min_cells: int = 3
    min_span_m: float = 1.5
    span_fraction: float = .40
    margin_m: float = .45
    margin_fraction: float = .12
    ground_min_points: int = 80
    ground_min_fraction: float = .35
    history_window_s: float = .35
    range_tolerance_m: float = .70


def corridor_from_course(course):
    """Require two unambiguous measured boundaries; never invent a width."""
    if course.get('state') != 'paired':
        return None
    lines = course.get('lines', {})
    if not all(name in lines for name in ('left', 'right')):
        return None
    theta = math.radians(course['heading_deg'])
    t = np.array([math.cos(theta), math.sin(theta)])
    n = np.array([-t[1], t[0]])
    rho = {}
    for name in ('left', 'right'):
        xy = -np.asarray(lines[name]['points_cm'], dtype=float).reshape(2, 3)[:, :2] / 100
        rho[name] = float(np.mean(xy @ n))
    width = rho['left'] - rho['right']
    if not 2 <= width <= 8:
        return None
    return dict(t=t, n=n, low=rho['right'], high=rho['left'], width=width,
                heading_deg=float(course['heading_deg']))


def detect_stop_row(xyz, plane, course, config=None):
    """Inspect original ROI returns, before any viewer downsampling."""
    cfg = config or StopRowConfig()
    result = dict(state='none', reason='no_corridor', source='sparse_occupancy', ground='unchecked')
    pair = corridor_from_course(course)
    if pair is None:
        return result
    xyz, plane = np.asarray(xyz), np.asarray(plane)
    if (xyz.ndim != 2 or xyz.shape[1] != 3 or plane.shape != (3,)
            or not np.isfinite(xyz).all() or not np.isfinite(plane).all()):
        raise ValueError('Invalid sparse-row points or plane')
    p = -xyz[:, :2]
    s, q = p @ pair['t'], p @ pair['n']
    h = heights_above_plane(xyz, plane)
    margin = max(cfg.margin_m, cfg.margin_fraction * pair['width'])
    inside = (q > pair['low'] + margin) & (q < pair['high'] - margin)
    # Reject a low-biased plane that turns normal near road into obstacles.
    # This checks independent raw returns, not only the plane fitter's inliers.
    near = inside & (s >= 2) & (s <= 18)
    ground = near & (np.abs(h) <= .07)
    count = int(ground.sum())
    fraction = count / max(1, int(near.sum()))
    coverage = len(np.unique(np.floor(s[ground] / 2)))
    result.update(ground_points=count, ground_fraction=round(fraction, 3))
    if count < cfg.ground_min_points or fraction < cfg.ground_min_fraction or coverage < 4:
        result.update(reason='ground_unreliable', ground='unreliable')
        return result
    result.update(reason='no_transverse_support', ground='near_verified')
    use = inside & (s >= cfg.range_min_m) & (s <= cfg.range_max_m) & (h > cfg.min_height_m) & (h <= cfg.max_height_m)
    s, q = s[use], q[use]
    if len(s) < cfg.min_cells:
        return result
    _, indices = np.unique(np.floor(np.column_stack((s, q)) / cfg.cell_m).astype(np.int32), axis=0, return_index=True)
    s, q = s[indices], q[indices]
    rows = []
    for offset in (0., cfg.depth_m / 2):
        bins = np.floor((s + offset) / cfg.depth_m).astype(np.int32)
        for band in np.unique(bins):
            mask = bins == band
            if mask.sum() < cfg.min_cells:
                continue
            ss, qq = s[mask], q[mask]
            cells = len(np.unique(np.floor(qq / cfg.cell_m).astype(np.int32)))
            span = float(np.ptp(qq))
            if cells < cfg.min_cells or span < max(cfg.min_span_m, cfg.span_fraction * pair['width']):
                continue
            distance = float(np.median(ss))
            xy = -(distance * pair['t'] + np.array([qq.min(), qq.max()])[:, None] * pair['n'])
            z = xy @ plane[:2] + plane[2] + .12
            rows.append(dict(distance_cm=round(distance * 100), support_cells=cells,
                             span_cm=round(span * 100),
                             points_cm=np.rint(np.column_stack((xy, z)) * 100).astype(int).ravel().tolist(),
                             lateral_center_m=(pair['low'] + pair['high']) / 2,
                             heading_deg=pair['heading_deg']))
    if rows:
        best = min(rows, key=lambda row: (row['distance_cm'], -row['support_cells']))
        result.update(best, state='candidate', reason='awaiting_repeat')
    return result


class StopRowTracker:
    """Two of three distinct scans, with bounded elapsed time and range rate.

    A repeated evaluation of the same latest scan replaces its evidence; it
    cannot count twice. Missing scans consume the window and clear the line.
    """
    def __init__(self, config=None):
        self.config = config or StopRowConfig()
        self.history = deque(maxlen=3)

    def update(self, row, time_s, frame_id, speed_mps):
        if self.history and time_s < self.history[-1]['time']:
            self.history.clear()
        if self.history and frame_id != self.history[-1]['id'] and any(frame_id == v['id'] for v in self.history):
            result = dict(row)
            if row.get('state') == 'candidate':
                result.update(state='candidate', reason='duplicate_scan', observations=1)
            return result
        if self.history and frame_id == self.history[-1]['id']:
            self.history.pop()
        result = dict(row)
        speed_ok = speed_mps is not None and math.isfinite(speed_mps) and speed_mps >= 0
        witnesses = 0
        if row.get('state') == 'candidate' and speed_ok:
            for earlier in list(self.history)[-2:]:
                old, dt = earlier['row'], time_s - earlier['time']
                if (not 0 < dt <= self.config.history_window_s or earlier['speed'] is None
                        or old.get('state') != 'candidate'):
                    continue
                moved = (speed_mps + earlier['speed']) * .5 * dt
                error = abs(row['distance_cm'] / 100 - (old['distance_cm'] / 100 - moved))
                if (error <= self.config.range_tolerance_m
                        and abs(row['lateral_center_m'] - old['lateral_center_m']) <= .75
                        and abs(row['heading_deg'] - old['heading_deg']) <= 6):
                    witnesses += 1
            if witnesses:
                result.update(state='confirmed', reason='range_rate_consistent')
        elif row.get('state') == 'candidate':
            result['reason'] = 'speed_unavailable'
        if row.get('state') == 'candidate':
            result['observations'] = 1 + witnesses
        self.history.append(dict(id=frame_id, time=time_s, speed=speed_mps if speed_ok else None, row=dict(row)))
        return result
