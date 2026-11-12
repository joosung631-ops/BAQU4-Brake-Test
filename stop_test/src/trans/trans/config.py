# ===== 공통 (trans_node.py) =====

# True면 터미널 출력만 하고 STM32로 실제 전송은 안 함. False면 출력 + 전송을
# 모두 함 - 하드웨어에 실제로 붙어서 테스트할 때만 False로 바꿀 것.
TEST_MODE = False

# manual_control이 [steering, speed, brake]를 발행하는 토픽 이름과 일치해야 함.
CMD_TOPIC = 'cmd'  

# 조향/모터/브레이크 세 보드가 모두 같은 포트에서 듣는다 (docs/2026-08-23-test
# 기준 확인됨).
VEHICLE_PORT = 5000




# ===== steer.py =====

# 조향팀 STM32의 UDP 수신 주소. 조향팀에서 전달받은 고정 IP - STM32는 DHCP를
# 안 쓰고 이 IP로 고정되어 있음.
STM32_IP = '10.177.21.4'
STM32_PORT = VEHICLE_PORT

# 공유 패킷(9바이트)의 steer 필드 범위(도, degree). steering(-1.0~1.0)을
# deg = -steering * STEER_DEG_MAX 로 변환한 뒤 이 범위로 clamp한다. 보드가 이
# float32 등가 조향각을 받아서 보정된 환산비로 모터 위치를 계산한다.
# 2026-10-22: GPS 원선회 기반 공통 등가 조향각 ±17.01 deg.
# PC 패킷 첫 4바이트는 little-endian float32 degree. 정규화 ±1 -> ∓17.01 deg.
STEER_DEG_MIN = -17.01
STEER_DEG_MAX = 17.01

# ASMS 패킷(모드 권한, 5바이트)은 trans_node.py가 안 보낸다. 개발 중에는
# tools/asms_heartbeat_stub.py로 이 패킷을 흉내 내서 테스트했었는데, 실제
# ASMS 보드/PC가 이 역할을 하게 되어 그 스텁은 지웠다. ASMS가 mode=1(AUTO)을
# 주기적으로 안 보내면 조향/브레이크 보드가 PC 명령 자체를 무시하므로(각
# 보드 펌웨어 참고), mode 하트비트를 계속 보내는 건 trans가 아니라 ASMS
# 쪽 책임이다(2026-08-23 확인).


# ===== motor.py =====

# Arduino UNO 모터 보드의 UDP 수신 주소.
MOTOR_IP = '10.177.21.2'
MOTOR_PORT = VEHICLE_PORT

# 2026-10-23 UNO 실제 RPM 계약: float32, 정수 반올림 없이 송신.
# speed = -speed_raw * 891.387 RPM. 0=정지, 기존 부호 반전 유지.
# GNSS 기준 실제 RPM -> 컨트롤러 단위 환산은 UNO의 CAN 송신 경계에서 수행.
MOTOR_SPEED_MIN = -891.387
MOTOR_SPEED_MAX = 891.387


# ===== brake.py =====

# 브레이크팀 STM32의 UDP 수신 주소. 실제 최신 펌웨어
# (docs/hardware_team_code/20260825_brake_code.txt의 localIp(10,177,21,3))로
# 확인됨 - 구 20260823 코드는 범용 템플릿이라 localIp가 .2(모터)로 잘못
# 박혀 있었는데, 이번 실제 브레이크 펌웨어에서 .3으로 바로잡혀 있다.
BRAKE_IP = '10.177.21.3'
BRAKE_PORT = VEHICLE_PORT

# 브레이크 전용 필드가 따로 있는 게 아니라, 9바이트 공유 패킷의 misc
# 바이트(마지막 1바이트) 중 bit 7이 브레이크 on/off를 나타낸다. 실제 최신
# 펌웨어(20260825_brake_code.txt)의 `(misc >> 7) & 0x01`로 최종 확인됨 -
# PACKET.md Q3에서 브레이크팀이 "0 또는 1"이라고 답했던 것은 misc 바이트
# 전체가 아니라 bit7 추출 결과(0 또는 1)를 말한 것으로 봐야 한다(실제 코드가
# bit7만 본다). 값 자체는 0/1 이분법이면 충분하다 - 아날로그처럼 세게/약하게는
# 없음.
MISC_BRAKE_BIT = 0x80
