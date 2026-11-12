"""ROS message construction kept separate from detection and the ROS executor."""
from copy import deepcopy

from .geometry import aabb, transform_points, validate_transform


def make_sensor_result(source_cloud, cones, processing_ok=True):
    from lidar_cone_msgs.msg import Cone3D, ConeDetections3D

    result = ConeDetections3D()
    result.header = deepcopy(source_cloud.header)
    result.valid = bool(processing_ok)
    if not processing_ok:
        return result
    for cone in cones:
        item = Cone3D()
        item.center.x, item.center.y, item.center.z = map(float, cone.center)
        item.size.x, item.size.y, item.size.z = map(float, cone.size)
        item.point_count = len(cone.points)
        result.objects.append(item)
    return result


def make_result(source_cloud, cones, transform=None, processing_ok=True):
    from control_manager.msg import LidarObject, LidarObjects

    result = LidarObjects()
    result.timestamp = deepcopy(source_cloud.header.stamp)
    result.valid = False
    result.objects = []
    if not processing_ok:
        return result
    # Validate even an empty list: no calibrated success without a transform.
    validate_transform(transform)
    objects = []
    for cone in cones:
        center, size = aabb(transform_points(cone.points, transform))
        item = LidarObject()
        item.center.x, item.center.y, item.center.z = map(float, center)
        item.size.x, item.size.y, item.size.z = map(float, size)
        objects.append(item)
    result.objects = objects
    result.valid = True
    return result


def make_markers(source_cloud, cones):
    from geometry_msgs.msg import Point
    from visualization_msgs.msg import Marker, MarkerArray

    markers = MarkerArray()
    clear = Marker()
    clear.header = deepcopy(source_cloud.header)
    clear.action = Marker.DELETEALL
    markers.markers.append(clear)
    for i, cone in enumerate(cones):
        marker = Marker()
        marker.header = deepcopy(source_cloud.header)
        marker.ns, marker.id = "sensor_cones", i * 2
        marker.type, marker.action = Marker.LINE_LIST, Marker.ADD
        marker.pose.orientation.w = 1.0
        marker.scale.x = 0.025
        marker.color.r, marker.color.g, marker.color.b, marker.color.a = 1.0, 0.55, 0.05, 1.0
        low, high = cone.center - cone.size / 2, cone.center + cone.size / 2
        vertices = [[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
        for start in range(8):
            for bit in (1, 2, 4):
                end = start ^ bit
                if start < end:
                    for index in (start, end):
                        marker.points.append(Point(x=float(vertices[index][0]), y=float(vertices[index][1]), z=float(vertices[index][2])))
        markers.markers.append(marker)
        label = Marker()
        label.header = deepcopy(source_cloud.header)
        label.ns, label.id = "sensor_cones", i * 2 + 1
        label.type, label.action = Marker.TEXT_VIEW_FACING, Marker.ADD
        label.pose.orientation.w = 1.0
        label.pose.position.x, label.pose.position.y = map(float, cone.center[:2])
        label.pose.position.z = float(high[2] + 0.18)
        label.scale.z = 0.18
        label.color.r, label.color.g, label.color.b, label.color.a = 1.0, 0.8, 0.2, 1.0
        label.text = "C{} {:.1f}m".format(i + 1, float(sum(cone.center[:2] ** 2) ** 0.5))
        markers.markers.append(label)
    return markers
