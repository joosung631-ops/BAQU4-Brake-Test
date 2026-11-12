"""Coordinate transforms and the exact handoff AABB contract."""
import json
from pathlib import Path

import numpy as np


def validate_transform(matrix):
    if matrix is None:
        raise ValueError("os_lidar -> base_link calibration is missing")
    transform = np.asarray(matrix, dtype=np.float64)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError("Transform must be a finite 4 x 4 matrix")
    if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-8, rtol=0):
        raise ValueError("Invalid homogeneous transform last row")
    rotation = transform[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0):
        raise ValueError("Rotation must be orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6, rtol=0):
        raise ValueError("Rotation must be right handed")
    return transform


def transform_points(points, matrix):
    transform = validate_transform(matrix)
    return np.asarray(points) @ transform[:3, :3].T + transform[:3, 3]


def aabb(points):
    points = np.asarray(points)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        raise ValueError("A nonempty N x 3 cluster is required")
    if not np.isfinite(points).all():
        raise ValueError("AABB points must be finite")
    low, high = points.min(axis=0), points.max(axis=0)
    return (low + high) / 2.0, high - low


def load_calibration(path, source_frame="os_lidar"):
    if not path:
        raise ValueError("No calibration_file configured; sensor coordinates are diagnostic only")
    document = json.loads(Path(path).read_text())
    if document.get("status") != "CALIBRATED":
        raise ValueError("Calibration status must explicitly be CALIBRATED")
    if document.get("source_frame") != source_frame or document.get("target_frame") != "base_link":
        raise ValueError("Calibration source/target frame does not match the point cloud")
    if document.get("translation_unit") != "m":
        raise ValueError("Calibration translation_unit must be m")
    return validate_transform(document.get("T_base_from_" + source_frame))


def quaternion_transform(translation, quaternion):
    q = np.asarray(quaternion, dtype=float)
    norm = np.linalg.norm(q)
    if not np.isfinite(norm) or norm < 1e-12:
        raise ValueError("Invalid TF quaternion")
    x, y, z, w = q / norm
    transform = np.eye(4)
    transform[:3, :3] = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    transform[:3, 3] = translation
    return validate_transform(transform)
