"""
조향 파트 - cmd 토픽의 steering 값을 9바이트 공유 패킷의 steer 필드로
변환한다. 패킷 자체는 trans_node.py가 조립해서 steer/motor/brake 세 주소에
동일하게 보낸다 (docs/2026-08-23-test 기준: 세 보드가 같은 9바이트를 받아서
각자 필요한 필드만 읽어 쓰는 구조).

STM32는 두 종류의 패킷을 받는다(조향팀 레퍼런스
docs/2026-08-23-test/steering_code_UDP_test.txt 기준): 실제 조향값을 담는
PC 패킷(9바이트)과, 자율주행 모드 진입 권한을 주는 ASMS 패킷(5바이트). 이
mode 하트비트를 주기적으로 보내는 건 trans 책임 범위 밖으로 확인됨(2026-08-23)
- 실제 ASMS 보드/PC가 담당한다. 개발 중 이 패킷을 흉내 내던
tools/asms_heartbeat_stub.py는 그 역할이 ASMS 쪽으로 넘어가면서 삭제됨.

steer 필드는 little-endian float32 도(degree) 단위다. 정규화 명령에
공통 최대 등가 조향각 17.01 deg와 -1을 곱하고 소수 각도를 유지하여 전송한다.
보드는 같은 등가 조향각 기준으로 모터 위치를 계산한다.
"""

import math

from trans import config

ADDR = (config.STM32_IP, config.STM32_PORT)


def to_deg(steering_raw: float) -> float:
    if not math.isfinite(steering_raw):
        raise ValueError('Steering command must be finite')
    scaled = -steering_raw * config.STEER_DEG_MAX
    return max(config.STEER_DEG_MIN, min(config.STEER_DEG_MAX, scaled))
