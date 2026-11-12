"""
브레이크 파트 - cmd 토픽의 brake 값을 9바이트 공유 패킷의 misc 바이트로
변환한다. 패킷 자체는 trans_node.py가 조립한다 (steer.py 모듈 docstring
참고).

브레이크 전용 필드가 따로 있는 게 아니라, misc 바이트(9바이트 중 마지막
1바이트)의 bit 7이 켜져 있으면 정지/브레이크로 해석된다 - 실제 브레이크
펌웨어(docs/hardware_team_code/20260825_brake_code.txt)의
`(misc >> 7) & 0x01`로 확인됨. 값 자체는 0/1 이분법이면 충분하다(실제
동작이 브레이크 잡기/안 잡기로만 나뉨).

⚠️ 이 misc 비트는 브레이크 보드가 ASMS 5바이트 패킷으로 받는 mode가 1(AUTO)일
때만 반영된다 - mode != 1이면 PC brake 명령 자체를 무시한다(20260825 코드의
"MODE 1이 아니면 PC brake 명령 무시" 로직). 이 mode 하트비트는 trans가 보내는
9바이트 패킷과는 별개이고, 주기적으로 보내는 책임은 trans가 아니라 ASMS
쪽이다(steer.py 모듈 docstring 참고) - ASMS가 AUTO를 안 걸어주면 여기서
misc를 아무리 올바르게 채워도 브레이크가 실제로는 걸리지 않으니, 실차
테스트 전에 ASMS 쪽이 이 하트비트를 실제로 보내고 있는지부터 확인할 것.
"""

from trans import config

ADDR = (config.BRAKE_IP, config.BRAKE_PORT)


def to_misc(brake_raw: float) -> int:
    return config.MISC_BRAKE_BIT if brake_raw else 0x00
