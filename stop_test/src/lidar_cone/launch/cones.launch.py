import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    share = get_package_share_directory("lidar_cone")
    arguments = [
        ("input_topic", "/lidar/points"),
        ("sensor_frame", "os_lidar"),
        ("output_topic", "/sensors/detectCone"),
        ("sensor_output_topic", "/perception/lidar/cones"),
        ("marker_topic", "/lidar/cones/markers"),
        ("detector_config", os.path.join(share, "config", "detector.yaml")),
        ("transform_source", "file"),
        ("calibration_file", ""),
        ("use_sim_time", "false"),
    ]
    declarations = [DeclareLaunchArgument(name, default_value=value) for name, value in arguments]
    parameters = {
        name: ParameterValue(LaunchConfiguration(name), value_type=str)
        for name, _ in arguments if name != "use_sim_time"
    }
    parameters["use_sim_time"] = ParameterValue(LaunchConfiguration("use_sim_time"), value_type=bool)
    return LaunchDescription(declarations + [Node(
        package="lidar_cone", executable="cone_detector", name="lidar_cone_detector",
        output="screen", parameters=[parameters],
    )])
