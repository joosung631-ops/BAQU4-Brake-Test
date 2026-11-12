# ===== motor_rpm_node.py =====

# 모터팀 STM32 주소. trans/config.py의 MOTOR_IP와 같은 보드다 - 보드 IP가
# 바뀌면 두 곳을 함께 고칠 것.
MOTOR_IP = '10.177.21.2'

# 모터 보드가 실제 RPM을 보내는 텔레메트리 포트. 명령 포트(trans의
# VEHICLE_PORT=5000)와 별개이며, 보드는 MOTOR_IP:MOTOR_RPM_PORT에서 PC의 같은
# 포트로 8바이트 패킷(<iI: int32 rpm, uint32 CAN 측정시각 ms)을 보낸다.
# 새 펌웨어용 계약이다. 기존 5바이트 <iB> 패킷은 지원하지 않는다.
MOTOR_RPM_BIND = '0.0.0.0'
MOTOR_RPM_PORT = 5001

# 컨트롤러 프로토콜상 RPM 범위. 벗어나면 잘못된 패킷으로 버린다.
MOTOR_RPM_LIMIT = 32000

# 이 시간 동안 정상 UDP가 없거나 MCU 측정시각이 진행하지 않으면 무효.
MOTOR_RPM_TIMEOUT_SEC = 0.5

# 값 / MCU 측정시각 / PC 측 유효성을 한 메시지로 발행한다.
MOTOR_FEEDBACK_TOPIC = '/motor_feedback'


# ===== steer_angle_node.py =====

# 조향팀 STM32 주소. trans/config.py의 STM32_IP와 같은 보드다 - 보드 IP가
# 바뀌면 두 곳을 함께 고칠 것. 보드는 STEER_IP:STEER_SRC_PORT(명령 수신
# 포트와 같은 5000)에서 PC(10.177.21.1)의 STEER_ANGLE_PORT로 보낸다.
STEER_IP = '10.177.21.4'
STEER_SRC_PORT = 5000
STEER_ANGLE_BIND = '0.0.0.0'
STEER_ANGLE_PORT = 5002

# 패킷 6바이트 '<hI': int16 조향각(값/100 = degree), uint32 측정 시각(MCU
# 부팅 후 ms). sequence나 상태 flags는 없다.
STEER_ANGLE_SCALE = 100.0

# 좌우 부호는 조향팀이 실기 확인 후 공유하기로 함(미확정). 확인되면 PC 쪽
# 규약과 반대일 때 -1로 바꿀 것.
STEER_ANGLE_SIGN = 1

# 송신 주기 목표 20ms(50Hz). 5주기 연속 못 받으면 무효로 본다. MCU 시각은
# PC와 동기화되지 않으므로 끊김·측정시각 정체 판단은 PC 시계로 한다.
STEER_ANGLE_TIMEOUT_SEC = 0.1

STEERING_FEEDBACK_TOPIC = '/steering_feedback'
