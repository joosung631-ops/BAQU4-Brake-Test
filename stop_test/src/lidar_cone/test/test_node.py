"""Exercise the actual ROS callback and generated wire types, without bag play."""
from pathlib import Path

import numpy as np


class Capture:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


def test_callback_calibration_failure_success_empty_and_bad_input(tmp_path, monkeypatch):
    import rclpy
    from rclpy.serialization import deserialize_message, serialize_message
    from sensor_msgs.msg import PointCloud2, PointField
    from control_manager.msg import LidarObjects
    from visualization_msgs.msg import Marker
    from lidar_cone.node import ConeDetectorNode

    monkeypatch.setenv("ROS_LOCALHOST_ONLY", "1")
    monkeypatch.setenv("ROS_LOG_DIR", str(tmp_path / "ros_logs"))
    context = rclpy.context.Context()
    rclpy.init(context=context, domain_id=133)
    node = None
    try:
        node = ConeDetectorNode(context=context)
        results, markers, sensor_results = Capture(), Capture(), Capture()
        node.result_publisher, node.marker_publisher = results, markers
        node.sensor_result_publisher = sensor_results
        sample = Path(__file__).resolve().parents[2] / "lidar_cone_handoff/samples/frame_018s.cdr"
        cloud = deserialize_message(sample.read_bytes(), PointCloud2)
        node.on_cloud(cloud)
        result = results.messages[-1]
        assert not result.valid and list(result.objects) == []
        assert sensor_results.messages[-1].valid
        assert sensor_results.messages[-1].header == cloud.header
        assert len(sensor_results.messages[-1].objects) > 0
        assert all(item.center.x < 0 for item in sensor_results.messages[-1].objects)
        assert result.timestamp == cloud.header.stamp
        assert len(markers.messages[-1].markers) > 1
        assert all(marker.header == cloud.header for marker in markers.messages[-1].markers)

        # This transform is synthetic test data, not a default vehicle extrinsic.
        node.transform = np.diag([-1.0, -1.0, 1.0, 1.0])
        node.on_cloud(cloud)
        result = deserialize_message(serialize_message(results.messages[-1]), LidarObjects)
        assert result.valid and len(result.objects) > 0
        # The synthetic rotation maps sensor-front (-X) to base-front (+X).
        assert all(item.center.x > 0 for item in result.objects)
        assert len(markers.messages[-1].markers) == 2 * len(result.objects) + 1
        assert result.timestamp == cloud.header.stamp

        rng = np.random.default_rng(42)
        road = np.column_stack([rng.uniform(-12, 10, 2000), rng.uniform(-5, 5, 2000), np.full(2000, -1.2)])
        empty = PointCloud2()
        empty.header.frame_id = "os_lidar"
        empty.header.stamp.sec = 5000
        empty.height, empty.width = 1, len(road)
        empty.fields = [PointField(name=name, offset=i * 4, datatype=PointField.FLOAT32, count=1) for i, name in enumerate(("x", "y", "z"))]
        empty.point_step, empty.row_step = 12, 12 * len(road)
        empty.data = road.astype("<f4").tobytes()
        node.on_cloud(empty)
        assert results.messages[-1].valid and list(results.messages[-1].objects) == []
        assert results.messages[-1].timestamp == empty.header.stamp
        assert len(markers.messages[-1].markers) == 1
        assert sensor_results.messages[-1].valid and list(sensor_results.messages[-1].objects) == []

        # A later corrupt frame must not re-publish the preceding good list.
        cloud.data = cloud.data[:10]
        cloud.header.stamp.nanosec += 1
        node.on_cloud(cloud)
        assert not results.messages[-1].valid and list(results.messages[-1].objects) == []
        assert results.messages[-1].timestamp == cloud.header.stamp
        assert len(markers.messages[-1].markers) == 1
        assert markers.messages[-1].markers[0].action == Marker.DELETEALL
        assert not sensor_results.messages[-1].valid and list(sensor_results.messages[-1].objects) == []
        empty.header.frame_id = "os_sensor"
        node.on_cloud(empty)
        assert not results.messages[-1].valid and list(results.messages[-1].objects) == []
        assert len(results.messages) == 5
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown(context=context)
