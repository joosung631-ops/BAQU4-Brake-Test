import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lidar_cone.detector import Cone
from lidar_cone.geometry import aabb, load_calibration, transform_points, validate_transform


def test_transform_then_aabb_uses_full_nonnegative_sizes_and_box_center():
    points = np.array([[1, 2, 3], [3, 5, 7], [1, 2, 3]])
    transform = np.array([[0, -1, 0, 10], [1, 0, 0, 20], [0, 0, 1, 30], [0, 0, 0, 1]])
    center, size = aabb(transform_points(points, transform))
    np.testing.assert_allclose(center, [6.5, 22, 35])
    np.testing.assert_allclose(size, [3, 2, 4])
    assert not np.allclose(center, transform_points(points, transform).mean(axis=0))
    with pytest.raises(ValueError):
        validate_transform(np.diag([-1, 1, 1, 1]))
    with pytest.raises(ValueError):
        validate_transform(None)


def test_arbitrary_rotation_recomputes_box_from_points_not_old_box():
    points = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0.2, 0.2, 1]])
    angle = np.pi / 4
    transform = np.array([[np.cos(angle), -np.sin(angle), 0, 0], [np.sin(angle), np.cos(angle), 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    _, size = aabb(transform_points(points, transform))
    np.testing.assert_allclose(size, [2 * np.sqrt(2), np.sqrt(2), 1])


def test_incomplete_calibration_is_never_zero_filled(tmp_path):
    template = Path(__file__).resolve().parents[2] / "lidar_cone_handoff/config/calibration_template.json"
    with pytest.raises(ValueError, match="CALIBRATED"):
        load_calibration(template)
    document = {"status": "CALIBRATED", "source_frame": "os_lidar", "target_frame": "base_link", "translation_unit": "m", "T_base_from_os_lidar": None}
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="missing"):
        load_calibration(path)
    document["T_base_from_os_lidar"] = np.eye(4).tolist()
    document["source_frame"] = "os_sensor"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="frame"):
        load_calibration(path)


def test_timestamp_empty_success_and_failure_contract():
    from builtin_interfaces.msg import Time
    from lidar_cone.messages import make_result

    source = SimpleNamespace(header=SimpleNamespace(stamp=Time(sec=4939, nanosec=301139460)))
    success = make_result(source, [], np.eye(4))
    assert success.valid and list(success.objects) == []
    failure = make_result(source, [], processing_ok=False)
    assert not failure.valid and list(failure.objects) == []
    for result in (success, failure):
        assert result.timestamp == source.header.stamp
        assert result.timestamp is not source.header.stamp
    with pytest.raises(ValueError):
        make_result(source, [], None)
    points = np.array([[-4, -1, -1], [-3.8, -0.8, -0.4]])
    center, size = aabb(points)
    transform = np.diag([-1.0, -1.0, 1.0, 1.0])
    # Synthetic test transform only, never installed as vehicle calibration.
    transform[0, 3] = 0.559
    result = make_result(source, [Cone(points, center, size, (0.1, 0.7))], transform)
    assert result.valid and len(result.objects) == 1
    assert result.objects[0].center.x > 0 and result.objects[0].center.y > 0
    assert result.objects[0].size.x == pytest.approx(0.2)
    assert result.timestamp == source.header.stamp


def test_markers_clear_previous_boxes_even_when_empty():
    from sensor_msgs.msg import PointCloud2
    from visualization_msgs.msg import Marker
    from lidar_cone.messages import make_markers

    cloud = PointCloud2()
    cloud.header.frame_id = "os_lidar"
    cloud.header.stamp.sec = 4947
    markers = make_markers(cloud, [])
    assert len(markers.markers) == 1
    assert markers.markers[0].action == Marker.DELETEALL
    assert markers.markers[0].header == cloud.header
