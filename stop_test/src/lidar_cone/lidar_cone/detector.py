"""Geometric baseline: robust road plane, XY components, cone shape checks.

All points and boxes stay in the incoming sensor axes. No extrinsic is inferred.
No deskew or temporal accumulation is applied; one scan produces one result.
"""
from dataclasses import asdict, dataclass, fields
from itertools import product

import numpy as np

from .geometry import aabb


class ProcessingError(ValueError):
    pass


@dataclass(frozen=True)
class DetectorConfig:
    x_min: float = -30.0
    x_max: float = 0.0
    y_abs_max: float = 8.0
    z_min: float = -3.0
    z_max: float = 4.0
    range_min: float = 0.8
    range_max: float = 35.0
    ground_fit_range: float = 18.0
    ground_cell_size: float = 1.2
    ground_distance: float = 0.07
    ground_max_tilt_deg: float = 20.0
    ground_min_points: int = 80
    ransac_iterations: int = 80
    obstacle_min_height: float = 0.09
    cluster_radius: float = 0.20
    cluster_radius_per_m: float = 0.012
    cluster_radius_max: float = 0.48
    min_points: int = 3
    min_rings: int = 2
    max_points: int = 600
    min_observed_height: float = 0.10
    max_observed_height: float = 0.95
    min_width: float = 0.015
    max_width: float = 0.70
    min_top_height: float = 0.28
    max_top_height: float = 1.05
    max_bottom_height: float = 0.38
    sensor_top_margin: float = 0.05

    def __post_init__(self):
        values = asdict(self)
        if not all(np.isfinite(value) for value in values.values()):
            raise ValueError("Detector parameters must be finite")
        for name in ("ground_min_points", "ransac_iterations", "min_points", "min_rings", "max_points"):
            if not isinstance(values[name], int) or values[name] < 1:
                raise ValueError(name + " must be a positive integer")
        if not (self.x_min < self.x_max and self.z_min < self.z_max):
            raise ValueError("ROI minima must be below maxima")
        if not (0 <= self.range_min < self.range_max and self.y_abs_max > 0):
            raise ValueError("Invalid range/lateral ROI")
        if not (0 < self.ground_distance < self.obstacle_min_height):
            raise ValueError("Ground threshold must be below obstacle_min_height")
        if not (0 < self.ground_max_tilt_deg < 60 and self.ground_fit_range > 0 and self.ground_cell_size > 0):
            raise ValueError("Invalid ground fitting configuration")
        if not (0 < self.cluster_radius <= self.cluster_radius_max and self.cluster_radius_per_m >= 0):
            raise ValueError("Invalid clustering radii")
        if not (0 <= self.min_width < self.max_width and 0 <= self.min_observed_height < self.max_observed_height):
            raise ValueError("Invalid cone dimensions")
        if not (0 <= self.max_bottom_height < self.max_top_height and 0 <= self.min_top_height < self.max_top_height):
            raise ValueError("Invalid cone ground-relative heights")
        if self.max_points < self.min_points:
            raise ValueError("max_points must be >= min_points")
        if self.sensor_top_margin < 0:
            raise ValueError("sensor_top_margin must be nonnegative")

    @classmethod
    def from_dict(cls, document):
        unknown = set(document) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError("Unknown detector parameters: " + ", ".join(sorted(unknown)))
        return cls(**document)


@dataclass
class Cone:
    points: np.ndarray
    center: np.ndarray
    size: np.ndarray
    ground_heights: tuple

    def to_dict(self):
        return {
            "center": self.center.tolist(), "size": self.size.tolist(),
            "point_count": len(self.points), "ground_heights": list(self.ground_heights),
        }


@dataclass
class DetectionFrame:
    cones: list
    roi_points: np.ndarray
    ground_mask: np.ndarray
    plane: np.ndarray
    statistics: dict


def heights_above_plane(points, plane):
    a, b, c = plane
    return (points[:, 2] - a * points[:, 0] - b * points[:, 1] - c) / np.sqrt(a * a + b * b + 1)


def fit_ground(points, config):
    nearby = points[np.linalg.norm(points[:, :2], axis=1) <= config.ground_fit_range]
    if len(nearby) < config.ground_min_points:
        raise ProcessingError("Too few points to estimate a road plane")
    # One lower return per XY cell avoids favoring a nearby wall/cone surface.
    cells = np.floor(nearby[:, :2] / config.ground_cell_size).astype(np.int32)
    _, inverse = np.unique(cells, axis=0, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    groups = np.split(order, np.flatnonzero(np.diff(inverse[order])) + 1)
    seeds = np.array([
        nearby[group[np.argsort(nearby[group, 2])[int(0.15 * (len(group) - 1))]]]
        for group in groups
    ])
    if len(seeds) < 6:
        raise ProcessingError("Road plane has insufficient spatial coverage")
    rng = np.random.default_rng(42)
    best_count, best_plane = 0, None
    max_slope = np.tan(np.deg2rad(config.ground_max_tilt_deg))
    for _ in range(config.ransac_iterations):
        sample = seeds[rng.choice(len(seeds), 3, replace=False)]
        design = np.column_stack([sample[:, :2], np.ones(3)])
        if abs(np.linalg.det(design)) < 0.02:
            continue
        plane = np.linalg.solve(design, sample[:, 2])
        # The road must be below the sensor. This is a fit sanity check, not a
        # base_link height or a mounting calibration.
        if np.linalg.norm(plane[:2]) > max_slope or not (-3.0 < plane[2] < -0.25):
            continue
        count = np.count_nonzero(np.abs(heights_above_plane(seeds, plane)) < config.ground_distance)
        if count > best_count:
            best_count, best_plane = count, plane
    if best_plane is None:
        raise ProcessingError("No plausible road plane found")
    plane = best_plane
    for _ in range(3):
        mask = np.abs(heights_above_plane(nearby, plane)) < config.ground_distance
        ground = nearby[mask]
        if len(ground) < config.ground_min_points:
            raise ProcessingError("Road fit has too few inliers")
        design = np.column_stack([ground[:, :2], np.ones(len(ground))])
        plane, _, rank, _ = np.linalg.lstsq(design, ground[:, 2], rcond=None)
        if rank < 3 or np.linalg.norm(plane[:2]) > max_slope or not (-3 < plane[2] < -0.25):
            raise ProcessingError("Road fit is degenerate or too steep")
    return plane


def cluster_xy(points, config):
    """Range-adaptive Euclidean components using a spatial hash (no SciPy).

    Cluster all above-ground heights together: a tall post/wall must not become
    a cone just because its top was cropped below the sensor or to cone height.
    """
    if not len(points):
        return []
    cell_size = config.cluster_radius_max
    cells = np.floor(points[:, :2] / cell_size).astype(np.int32)
    buckets = {}
    for i, cell in enumerate(cells):
        buckets.setdefault(tuple(cell), []).append(i)
    buckets = {key: np.array(indices, dtype=np.int32) for key, indices in buckets.items()}
    radii = np.minimum(
        config.cluster_radius_max,
        config.cluster_radius + config.cluster_radius_per_m * np.linalg.norm(points[:, :2], axis=1),
    )
    visited = np.zeros(len(points), dtype=bool)
    offsets = tuple(product((-1, 0, 1), repeat=2))
    clusters = []
    for seed in range(len(points)):
        if visited[seed]:
            continue
        visited[seed] = True
        component, queue = [], [seed]
        while queue:
            i = queue.pop()
            component.append(i)
            cell_x, cell_y = cells[i]
            for dx, dy in offsets:
                candidates = buckets.get((cell_x + dx, cell_y + dy))
                if candidates is None:
                    continue
                candidates = candidates[~visited[candidates]]
                if not len(candidates):
                    continue
                delta = points[candidates, :2] - points[i, :2]
                # min makes the edge relation symmetric even across ranges.
                threshold = np.minimum(radii[i], radii[candidates])
                hits = candidates[np.einsum("ij,ij->i", delta, delta) <= threshold ** 2]
                visited[hits] = True
                queue.extend(hits.tolist())
        if config.min_points <= len(component) <= config.max_points:
            clusters.append(np.array(component))
    return clusters


class ConeDetector:
    def __init__(self, config=None):
        self.config = config or DetectorConfig()

    def detect(self, points, attributes=None, *, ground_plane=None):
        config = self.config
        points = np.asarray(points, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ProcessingError("Expected N x 3 XYZ points")
        attributes = attributes or {}
        if any(len(value) != len(points) for value in attributes.values()):
            raise ProcessingError("Point attribute length mismatch")
        ranges = np.linalg.norm(points, axis=1)
        keep = (
            np.isfinite(points).all(axis=1)
            & (ranges >= config.range_min) & (ranges <= config.range_max)
            & (points[:, 0] >= config.x_min) & (points[:, 0] <= config.x_max)
            & (np.abs(points[:, 1]) <= config.y_abs_max)
            & (points[:, 2] >= config.z_min) & (points[:, 2] <= config.z_max)
        )
        roi = points[keep]
        attrs = {key: np.asarray(value)[keep] for key, value in attributes.items()}
        # The viewer can share this scan's fit with its 10Hz foreground path.
        # Default callers still estimate exactly the same plane as before.
        plane = fit_ground(roi, config) if ground_plane is None else np.asarray(ground_plane, dtype=float).copy()
        if (plane.shape != (3,) or not np.isfinite(plane).all()
                or np.linalg.norm(plane[:2]) > np.tan(np.deg2rad(config.ground_max_tilt_deg))
                or not -3 < plane[2] < -.25):
            raise ProcessingError('Invalid supplied ground plane')
        height = heights_above_plane(roi, plane)
        foreground = height > config.obstacle_min_height
        # Do not crop foreground at max_top_height; tall objects must be rejected.
        objects = roi[foreground]
        object_heights = height[foreground]
        rings = attrs.get("ring")
        rings = rings[foreground] if rings is not None else None
        components = cluster_xy(objects, config)
        sensor_height = -plane[2] / np.sqrt(1.0 + np.dot(plane[:2], plane[:2]))
        below_sensor_limit = sensor_height - config.sensor_top_margin
        above_sensor_components = 0
        cones = []
        for indices in components:
            cluster = objects[indices]
            center, size = aabb(cluster)
            low_h, high_h = float(object_heights[indices].min()), float(object_heights[indices].max())
            # Compare signed distances along the estimated road normal. Raw
            # sensor Z can be positive for a low cone ahead when the sensor is
            # pitched. Keep complete clusters to reject tall structures intact.
            if high_h > below_sensor_limit:
                above_sensor_components += 1
                continue
            if not (config.min_observed_height <= high_h - low_h <= config.max_observed_height):
                continue
            if not (config.min_width <= max(size[:2]) <= config.max_width):
                continue
            if not (config.min_top_height <= high_h <= config.max_top_height and low_h <= config.max_bottom_height):
                continue
            if high_h - low_h < 0.65 * max(size[:2]):
                continue
            if rings is not None and len(np.unique(rings[indices])) < config.min_rings:
                continue
            # Reject dense inverted/flared shapes; do not impose an unmeasured
            # physical cone size or inflate sparse observations to that size.
            if len(cluster) >= 15:
                h = object_heights[indices]
                lower = cluster[h <= low_h + 0.4 * (high_h - low_h)]
                upper = cluster[h >= low_h + 0.6 * (high_h - low_h)]
                if len(lower) >= 3 and len(upper) >= 3:
                    lower_width = np.linalg.norm(np.ptp(lower[:, :2], axis=0))
                    upper_width = np.linalg.norm(np.ptp(upper[:, :2], axis=0))
                    if upper_width > 1.5 * lower_width + 0.08:
                        continue
            cones.append(Cone(cluster.copy(), center, size, (low_h, high_h)))
        cones.sort(key=lambda cone: float(np.linalg.norm(cone.center[:2])))
        ground_mask = np.abs(height) <= config.ground_distance
        statistics = {
            "input_points": len(points), "roi_points": len(roi),
            "ground_points": int(ground_mask.sum()), "foreground_points": len(objects),
            "candidate_components": len(components), "cones": len(cones),
            "sensor_height_above_plane_m": float(sensor_height),
            "cone_top_limit_above_plane_m": float(below_sensor_limit),
            "above_sensor_components": above_sensor_components,
        }
        return DetectionFrame(cones, roi, ground_mask, plane, statistics)
