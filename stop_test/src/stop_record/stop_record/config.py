# ===== record_node.py =====
# main/src/record/record/config.py를 stop_test 전용으로 복사해 수정 (2026-10-28).

# 저장 경로의 기준 폴더. stop_test 컨테이너의 /workspace = 호스트 2026WS/stop_test.
# 호스트 경로는 2026WS/stop_test/bags/ (.gitignore 대상).
RECORD_BASE_DIR = '/workspace/bags'

# stop_test 실행 기록 폴더. 녹화 중에 동작한 시험 ID를 description에 자동으로 적는다.
STOP_TEST_RUN_DIR = '/workspace/log/stop-test-cmd'

# 녹화 저장 포맷/압축. main의 record와 같게 유지 (기존 분석 도구 호환).
RECORD_STORAGE_FORMAT = 'sqlite3'
RECORD_COMPRESSION_MODE = 'file'  # 'none' | 'file' | 'message'
RECORD_COMPRESSION_FORMAT = 'zstd'

# --ros-args -p profile:=... 로 안 넘기면 쓸 기본 프로필 이름
DEFAULT_PROFILE = 'brake_test'

# 토픽이 그래프에 보여도 데이터가 안 올 수 있다 (main과 /dev/shm이 분리된 컨테이너에서
# FastDDS 기본 전송을 쓰면 실제로 그랬음, test_runs/sensor-cross-container-check-*).
# 그래서 'flow_check' 토픽은 이 시간 안에 실제 메시지를 1개 이상 받아야 녹화를 시작한다.
FLOW_CHECK_TIMEOUT_SEC = 3.0

# 녹화 설정 목록. 프로필 이름이 곧 저장 폴더 이름이 되고, 그 안에
# <프로필이름>_1, <프로필이름>_2, ... 순서로 매 실행마다 번호가 붙어 쌓인다.
RECORD_PROFILES = {
    # 2026-10-30: 카메라·IMU 없이 시험한다. 관련 항목은 삭제하지 않고 주석으로 보존한다.
    # /lidar/imu도 녹화에서 제외하며, 다시 사용할 때 아래 주석을 해제한다.
    # 제동 파라미터 분석용 (두 브레이크 펌웨어 공통). 활성 토픽은 모두 있어야 시작한다.
    'brake_test': {
        'topics': [
            '/tf_static',
            # '/camera/image_raw/compressed',
            '/lidar/points', '/lidar/metadata',
            # '/lidar/imu',
            '/gnss/fix', '/gnss/odom', '/gnss/status',
            # '/imu/data', '/imu/rpy',
            '/motor_feedback', '/steering_feedback',
            '/cmd',                     # 브레이크 명령 시각 (stop_test 주행 노드)
            '/vehicle/command_events',  # trans가 UDP를 실제로 보낸 시각
        ],
        'flow_check': {
            '/lidar/points': 'sensor_msgs/msg/PointCloud2',
            '/gnss/odom': 'nav_msgs/msg/Odometry',
            # '/imu/data': 'sensor_msgs/msg/Imu',
            '/cmd': 'std_msgs/msg/Float32MultiArray',
            '/vehicle/command_events': 'vehicle_recorder/msg/CommandEvent',
        },
    },
    # 카메라·IMU·trans 송신 이벤트가 없을 때의 최소 구성.
    'brake_test_core': {
        'topics': [
            '/tf_static',
            '/lidar/points', '/lidar/metadata',
            '/gnss/fix', '/gnss/odom', '/gnss/status',
            # '/imu/data',
            '/motor_feedback',
            '/cmd',
        ],
        'flow_check': {
            '/lidar/points': 'sensor_msgs/msg/PointCloud2',
            '/gnss/odom': 'nav_msgs/msg/Odometry',
            '/cmd': 'std_msgs/msg/Float32MultiArray',
        },
    },
}

# 녹화 종료 후 description.txt에 받을 항목 (그냥 엔터면 '(작성 안 함)').
DESCRIPTION_FIELDS = [
    ('firmware', '브레이크 펌웨어 (예: 1027 / 1028)'),
    ('brake_set', '1028 set 값과 응답 (예: full 35 release 75 hold 300 Applied)'),
    ('gap_m', '줄자로 잰 정지 간격 m (차 앞끝 → 정지열)'),
    ('note', '기타 메모 (속도 설정, 슬립/회전, 노면 등)'),
]
