import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
)
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description() -> LaunchDescription:
    sensor_hostname_arg = DeclareLaunchArgument(
        'sensor_hostname', default_value='192.168.100.50',
        description='Ouster OS1 IP/호스트명 (대시보드에서 확인한 고정 IP)',
    )
    udp_dest_arg = DeclareLaunchArgument(
        'udp_dest', default_value='192.168.100.1',
        description='라이다가 UDP 데이터를 보낼 호스트(이 컴퓨터) IP',
    )
    lidar_mode_arg = DeclareLaunchArgument(
        'lidar_mode', default_value='1024x10',
        description='수평 해상도 x 회전 속도(Hz)',
    )
    # RNG19_RFL8_SIG16_NIR16으로 시도했다가 'Field WINDOW not found in
    # LidarScan'로 드라이버가 죽음. ouster_ros 소스(sensor_point_types.h)를
    # 보면 이 프로파일은 WINDOW 필드가 있다고 가정하는데, WINDOW는 최신
    # 펌웨어 기능이라 우리 센서(FW 2.5.3)는 이 필드를 안 채워서 생기는
    # 버전 호환성 문제로 확인함. LEGACY는 WINDOW를 참조하지 않아 문제 없음.
    udp_profile_lidar_arg = DeclareLaunchArgument(
        'udp_profile_lidar', default_value='LEGACY',
        description='센서 펌웨어(2.5.3)가 오래돼 최신 프로파일의 WINDOW 필드를 못 채움 → LEGACY 사용',
    )
    viz_arg = DeclareLaunchArgument(
        'viz', default_value='false',
        description='true로 주면 ouster_ros가 제공하는 rviz2도 같이 실행',
    )

    # PointCloud2가 raw 이미지(camera 패키지 참고)보다도 커서(실측 1.57MB)
    # DDS 기본 UDP 전송으로는 대역폭이 심하게 병목남(목표 15.7MB/s인데
    # 2~3MB/s에서 정체). camera_node.py와 같은 이유로 SHM transport를
    # 이 launch로 띄우는 프로세스에 한해서만 적용.
    shm_profile_path = os.path.join(
        get_package_share_directory('lidar'), 'config', 'fastdds_shm_profile.xml',
    )
    set_shm_profile_env = SetEnvironmentVariable(
        'FASTRTPS_DEFAULT_PROFILES_FILE', shm_profile_path,
    )

    # 드라이버 코드를 직접 짜지 않고, Ouster 공식 드라이버(ouster_ros)의
    # launch 파일을 그대로 불러와 이 프로젝트에 맞는 인자만 덮어씀.
    ouster_sensor_launch = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('ouster_ros'),
                'launch', 'sensor.launch.xml',
            )
        ),
        launch_arguments={
            # ouster_ns가 곧 토픽 네임스페이스가 되므로, 이걸 'lidar'로
            # 주면 다른 리맵 없이 바로 /lidar/points로 발행됨
            'ouster_ns': 'lidar',
            'sensor_hostname': LaunchConfiguration('sensor_hostname'),
            'udp_dest': LaunchConfiguration('udp_dest'),
            'lidar_mode': LaunchConfiguration('lidar_mode'),
            'udp_profile_lidar': LaunchConfiguration('udp_profile_lidar'),
            # SCAN(LaserScan)/TLM(텔레메트리)는 여전히 안 쓰지만, IMU에 이어
            # IMG(range/signal/reflec/nearir 이미지)도 토픽으로 발행하도록 켬
            'proc_mask': 'PCL|IMU',
            'viz': LaunchConfiguration('viz'),
        }.items(),
    )

    return LaunchDescription([
        sensor_hostname_arg,
        udp_dest_arg,
        lidar_mode_arg,
        udp_profile_lidar_arg,
        viz_arg,
        set_shm_profile_env,
        ouster_sensor_launch,
    ])
