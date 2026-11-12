from dataclasses import fields
from pathlib import Path
from time import perf_counter

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import PointCloud2
from visualization_msgs.msg import MarkerArray
import yaml

from control_manager.msg import LidarObjects
from lidar_cone_msgs.msg import ConeDetections3D
from .detector import ConeDetector, DetectorConfig
from .geometry import load_calibration, quaternion_transform
from .messages import make_markers, make_result, make_sensor_result
from .pointcloud import decode_cloud


class ConeDetectorNode(Node):
    def __init__(self, **kwargs):
        super().__init__("lidar_cone_detector", **kwargs)
        for name, value in [
            ("input_topic", "/lidar/points"), ("output_topic", "/sensors/detectCone"),
            ("sensor_frame", "os_lidar"), ("detector_config", ""),
            ("transform_source", "file"), ("calibration_file", ""),
            ("marker_topic", "/lidar/cones/markers"),
            ("sensor_output_topic", "/perception/lidar/cones"),
        ]:
            self.declare_parameter(name, value)
        config_path = self.get_parameter("detector_config").value
        configured = yaml.safe_load(Path(config_path).read_text()) if config_path else {}
        config = DetectorConfig.from_dict(configured or {})
        values = {}
        for field in fields(config):
            self.declare_parameter("detector." + field.name, getattr(config, field.name))
            values[field.name] = self.get_parameter("detector." + field.name).value
        self.detector = ConeDetector(DetectorConfig.from_dict(values))
        self.sensor_frame = self.get_parameter("sensor_frame").value
        self.transform_source = self.get_parameter("transform_source").value
        self.transform = None
        self.calibration_error = ""
        self.tf_buffer, self.tf_listener = None, None
        if self.transform_source == "file":
            try:
                self.transform = load_calibration(self.get_parameter("calibration_file").value, self.sensor_frame)
            except (ValueError, OSError) as error:
                self.calibration_error = str(error)
                self.get_logger().warning(self.calibration_error + "; publishing valid=false and sensor-frame markers")
        elif self.transform_source == "tf":
            from tf2_ros import Buffer, TransformListener
            self.tf_buffer = Buffer()
            self.tf_listener = TransformListener(self.tf_buffer, self)
        else:
            raise ValueError("transform_source must be file or tf")
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST, depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE,
        )
        self.result_publisher = self.create_publisher(LidarObjects, self.get_parameter("output_topic").value, qos)
        self.sensor_result_publisher = self.create_publisher(ConeDetections3D, self.get_parameter("sensor_output_topic").value, qos)
        self.marker_publisher = self.create_publisher(MarkerArray, self.get_parameter("marker_topic").value, qos)
        self.subscription = self.create_subscription(
            PointCloud2, self.get_parameter("input_topic").value, self.on_cloud, qos,
        )
        self.received_frames = 0
        self.get_logger().info("Ready: frame=" + self.sensor_frame + ", vehicle forward is os_lidar -X")

    def lookup_transform(self, cloud):
        if self.tf_buffer is None:
            if self.transform is None:
                raise ValueError(self.calibration_error)
            return self.transform
        # Acquisition time, target=base_link, source=actual input frame. Never
        # fall back to the latest dynamic transform or an invented nominal TF.
        stamped = self.tf_buffer.lookup_transform(
            "base_link", cloud.header.frame_id,
            Time.from_msg(cloud.header.stamp), timeout=Duration(seconds=0.0),
        )
        tr, q = stamped.transform.translation, stamped.transform.rotation
        return quaternion_transform([tr.x, tr.y, tr.z], [q.x, q.y, q.z, q.w])

    def on_cloud(self, cloud):
        started = perf_counter()
        cones = []
        processing_ok = False
        error_text = ""
        try:
            if cloud.header.frame_id != self.sensor_frame:
                raise ValueError("Unexpected input frame: " + cloud.header.frame_id)
            xyz, attributes = decode_cloud(cloud)
            frame = self.detector.detect(xyz, attributes)
            cones = frame.cones
            processing_ok = True
        except Exception as error:
            error_text = "Detection failed: " + str(error)
        result = make_result(cloud, [], processing_ok=False)
        if processing_ok:
            try:
                result = make_result(cloud, cones, self.lookup_transform(cloud))
            except Exception as error:
                error_text = "base_link result unavailable: " + str(error)
        # One result per processed input, including empty/failure. No timer and
        # no cached detections can re-emit an old scan as a new observation.
        self.result_publisher.publish(result)
        self.sensor_result_publisher.publish(make_sensor_result(cloud, cones, processing_ok))
        self.marker_publisher.publish(make_markers(cloud, cones))
        if error_text:
            self.get_logger().warning(error_text, throttle_duration_sec=5.0)
        self.received_frames += 1
        if self.received_frames % 100 == 0:
            self.get_logger().info(
                "frames={} cones={} control_valid={} processing_ms={:.1f}".format(
                    self.received_frames, len(cones), result.valid, (perf_counter() - started) * 1000,
                )
            )


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = ConeDetectorNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
