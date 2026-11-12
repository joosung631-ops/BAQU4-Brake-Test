#!/usr/bin/env python3
"""
trans 패키지의 ROS2 노드.

수동 또는 자율 제어의 cmd 토픽(std_msgs/Float32MultiArray,
[steering, speed, brake] 순서, steering/speed는 -1.0~1.0, brake는 0/1)을
구독해서 9바이트 공유 패킷(steer: float32 도 단위, speed: float32 실제 RPM, misc:
uint8 브레이크 비트) 하나를 조립하고, 조향/모터/브레이크 세 보드가 같은
패킷을 받아 각자 필요한 필드만 읽어 쓰는 구조라 동일한 바이트를 세 주소에
그대로 보낸다(docs/hardware_team_code 기준. steer.py/motor.py 모듈 docstring 참고).
값 변환(조향·모터 부호 반전/스케일/클램프)은 steer.py/motor.py/brake.py로 분리되어 있고, 이
노드는 매 cmd 콜백마다 세 모듈을 호출해 패킷을 조립하고 전송하기만 한다.

config.TEST_MODE가 True면 터미널 출력만 하고 실제로는 전송하지 않는다.
False면 출력 + 전송을 모두 한다.
"""

import socket
import struct

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray
from vehicle_recorder.msg import CommandEvent  # 고규범 수정 (2026-10-21): reusable send timing.

from trans import brake, config, motor, steer


class TransNode(Node):
    def __init__(self):
        super().__init__('trans_node')

        self.declare_parameter('cmd_topic', config.CMD_TOPIC)
        # 고규범 신규 로직: TEST_MODE can be overridden in isolated tests without editing config.
        self.declare_parameter('test_mode', config.TEST_MODE)
        self._test_mode = self.get_parameter('test_mode').value
        self.declare_parameter('command_events_topic', '/vehicle/command_events')
        self._event_pub = self.create_publisher(CommandEvent, self.get_parameter('command_events_topic').value, 100)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._addrs = (steer.ADDR, motor.ADDR, brake.ADDR)

        # 고규범 수정: self.create_subscription(...) was previously not retained.
        self._command_sub = self.create_subscription(
            Float32MultiArray,
            self.get_parameter('cmd_topic').value,
            self._on_cmd,
            10,
        )

        self.get_logger().info(
            f"trans 노드 시작 - '{self.get_parameter('cmd_topic').value}' 구독 중"
        )

    def _on_cmd(self, msg: Float32MultiArray) -> None:
        steering_raw, speed_raw, brake_raw = msg.data[0], msg.data[1], msg.data[2]

        deg = steer.to_deg(steering_raw)
        speed = motor.to_speed_raw(speed_raw)
        misc = brake.to_misc(brake_raw)

        # 세 보드가 같은 9바이트를 받아서 각자 필요한 필드만 읽어 쓰는
        # 구조라, 패킷은 한 번만 조립해서 세 주소에 동일하게 보낸다.
        # 조향은 degree, 속도는 실제 RPM float32. UNO가 CAN 단위 환산/반올림한다.
        packet = struct.pack('<ffB', deg, speed, misc)

        # 고규범 수정 (2026-10-21): original transmission had no event timestamp.
        # if not config.TEST_MODE:
        #     for addr in self._addrs:
        #         self._sock.sendto(packet, addr)
        # 고규범 신규 로직: do not report successful transmission before all sends complete.
        send_stamp = self.get_clock().now().to_msg()
        if not self._test_mode:
            for addr in self._addrs:
                self._sock.sendto(packet, addr)
        event = CommandEvent(command_topic=self._command_sub.topic_name,
                             stage=CommandEvent.DRY_RUN if self._test_mode else CommandEvent.TRANSMITTED,
                             steering_raw=steering_raw, speed_raw=speed_raw, brake=bool(brake_raw))
        event.header.stamp = send_stamp
        event.header.frame_id = 'base_link'
        self._event_pub.publish(event)

        # raw/전송값 필드 너비를 고정해서(steering/speed: -1.0000~1.0000은
        # 항상 7자) 숫자 자리수가 바뀌어도 뒤 텍스트가 밀리지 않게 한다.
        print(
            # 고규범 수정: f'\r{"[TEST] " if config.TEST_MODE else ""}'
            f'\r{"[TEST] " if self._test_mode else ""}'
            f'steering  raw: {steering_raw:+7.4f} | deg: {deg:+9.5f}    '
            f'speed  raw: {speed_raw:+7.4f} | sent: {speed:+11.6f}    '
            f'brake: {int(bool(brake_raw))}',
            end='', flush=True,
        )

    def destroy_node(self):
        self._sock.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = TransNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        print()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
