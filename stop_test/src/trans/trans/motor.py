"""
모터 파트 - cmd 토픽의 speed 값을 9바이트 공유 패킷의 speed 필드로
변환한다. 패킷 자체는 trans_node.py가 조립한다 (steer.py 모듈 docstring
참고).

speed 필드는 2026-10-23 UNO 기준 실제 목표 RPM float32, -891.387~891.387.
- speed  > 0 : 음수 PC 지령에 대응하는 하드웨어 값
- speed  = 0 : 정지
- speed  < 0 : 양수 PC 지령에 대응하는 하드웨어 값
(모터 보드는 실제 목표 RPM의 부호를 뒤집고 CAN 송신 직전에 컨트롤러 단위로 환산한다.)

cmd 토픽의 speed_raw(-1.0~1.0)에 -891.387을 곱해 실제 RPM으로 보낸다.
입력 +1은 -891.387 RPM, 입력 -1은 +891.387 RPM으로 전송된다.

PC에서는 정수 반올림을 하지 않는다. 최종 CAN 정수 RPM 반올림은 모터 보드가 한다.
"""

import math

from trans import config

ADDR = (config.MOTOR_IP, config.MOTOR_PORT)


def to_speed_raw(speed_raw: float) -> float:
    """Convert normalized input to signed actual RPM for the UDP speed field."""
    if not math.isfinite(speed_raw):
        raise ValueError('Motor speed must be finite')
    scaled = -speed_raw * config.MOTOR_SPEED_MAX
    return max(config.MOTOR_SPEED_MIN, min(config.MOTOR_SPEED_MAX, scaled))
