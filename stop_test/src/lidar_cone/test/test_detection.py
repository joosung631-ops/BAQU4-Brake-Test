import numpy as np
import pytest

from lidar_cone.detector import ConeDetector, DetectorConfig, ProcessingError


def scene(include_cone=True, include_post=True):
    rng = np.random.default_rng(17)
    xy = rng.uniform([-15, -6], [8, 6], (2500, 2))
    ground_z = lambda points: -1.2 + 0.04 * points[:, 0] - 0.015 * points[:, 1]
    road = np.column_stack([xy, ground_z(xy) + rng.normal(0, 0.004, len(xy))])
    objects = [road]
    if include_cone:
        levels = np.linspace(0.1, 0.65, 14)
        cone = []
        for height in levels:
            theta = np.linspace(0, 2 * np.pi, 14, endpoint=False)
            radius = 0.16 * (1 - height / 0.75)
            xy = np.column_stack([-6 + radius * np.cos(theta), 2 + radius * np.sin(theta)])
            cone.append(np.column_stack([xy, ground_z(xy) + height]))
        objects.extend(cone)
    if include_post:
        theta = np.linspace(0, 2 * np.pi, 8, endpoint=False)
        for height in np.linspace(0.1, 2.5, 30):
            xy = np.column_stack([-9 + 0.09 * np.cos(theta), -2 + 0.09 * np.sin(theta)])
            objects.append(np.column_stack([xy, ground_z(xy) + height]))
    return np.concatenate(objects)


def test_tilted_road_separates_cone_and_rejects_tall_post():
    result = ConeDetector().detect(scene())
    np.testing.assert_allclose(result.plane, [0.04, -0.015, -1.2], atol=0.01)
    assert len(result.cones) == 1
    np.testing.assert_allclose(result.cones[0].center[:2], [-6, 2], atol=0.04)
    assert result.cones[0].size[2] > 0.5
    # Sensor axes are retained: a cone in front still has negative X.
    assert result.cones[0].center[0] < 0


def test_processed_no_cones_is_distinct_from_failed_ground_fit():
    detector = ConeDetector()
    assert detector.detect(scene(include_cone=False)).cones == []
    with pytest.raises(ProcessingError):
        detector.detect(np.zeros((20, 3)))


def test_bad_configuration_is_rejected():
    with pytest.raises(ValueError):
        DetectorConfig(x_min=5, x_max=-5)
    with pytest.raises(ValueError):
        DetectorConfig(cluster_radius_max=0)
    with pytest.raises(ValueError):
        DetectorConfig.from_dict({"typo": 1})
    with pytest.raises(ValueError):
        DetectorConfig(sensor_top_margin=-0.1)


def test_rear_cone_is_outside_front_roi():
    original = scene(include_post=False)
    # Mirroring the complete scene places its only cone behind the sensor.
    original[:, 0] *= -1
    assert ConeDetector().detect(original).cones == []


def test_pitched_sensor_keeps_low_cone_with_positive_raw_z():
    original = scene(include_post=False)
    # Shift the scene farther forward, then change the road slope. This is an
    # equivalent low cone on a flat road observed with a pitched sensor.
    original[:, 0] -= 8.0
    old_ground = -1.2 + 0.04 * (original[:, 0] + 8.0) - 0.015 * original[:, 1]
    original[:, 2] += (-1.2 - 0.08 * original[:, 0]) - old_ground
    frame = ConeDetector().detect(original)
    assert len(frame.cones) == 1
    assert frame.cones[0].points[:, 2].max() > 0
    assert frame.cones[0].ground_heights[1] < frame.statistics["cone_top_limit_above_plane_m"]


def test_above_sensor_cluster_is_rejected_without_clipping_its_top():
    original = scene(include_post=False)
    # Stretch only the cone (points after the 2500 road returns) to 1.4 m.
    cluster = original[2500:]
    ground = -1.2 + 0.04 * cluster[:, 0] - 0.015 * cluster[:, 1]
    cluster[:, 2] = ground + (cluster[:, 2] - ground) * (1.4 / 0.65)
    config = DetectorConfig(max_observed_height=1.6, max_top_height=1.8)
    frame = ConeDetector(config).detect(original)
    assert frame.cones == []
    assert frame.statistics["above_sensor_components"] > 0
