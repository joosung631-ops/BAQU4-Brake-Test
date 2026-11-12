#!/usr/bin/env python3
"""
조향 보드의 엔코더 조향각 피드백을 UDP로 받아 ROS2 토픽으로 발행하는 노드.
이 노드는 수신만 하고 제어 명령은 보내지 않는다.

패킷(6바이트, little-endian '<hI', 조향팀 사양):
- angle_raw      : int16, 값 / 100 = degree
- sample_time_ms : uint32, 해당 각도의 측정 시각(MCU 부팅 후 ms)

발행 토픽: /steering_feedback (encoder_motor/msg/SteeringFeedback)
- steer_angle: 현재 조향각 [degree]
- steer_angle_mcu_ms: 같은 패킷의 MCU 측정 시각
- steer_angle_valid: PC 수신·측정시각 진행 여부에 따른 유효성
UDP 수신 중단 또는 측정시각 정체 시 마지막 값과 시각을 유지한 채
valid=false를 한 번 발행한다.

조향각은 부팅·엔코더 리셋 위치를 0°로 하는 상대각이다. MCU 시각은 PC와
동기화되지 않고 재부팅 시 0부터 다시 시작하며 약 49.7일마다 순환하므로, 끊김
판단은 PC 시계로 하고 MCU 시각이 뒤로 가면 재부팅(= 0° 기준 리셋) 가능성을
경고만 한다.
"""

import socket
import struct
import time

import rclpy
from rclpy.node import Node
from encoder_motor import config
from encoder_motor.feedback_freshness import FeedbackFreshness
from encoder_motor.msg import SteeringFeedback

PACKET = struct.Struct('<hI')


def decode_packet(data: bytes):
    if len(data) != PACKET.size:
        raise ValueError(f'Expected exactly {PACKET.size} bytes, got {len(data)}')
    angle_raw, sample_time_ms = PACKET.unpack(data)
    return angle_raw / config.STEER_ANGLE_SCALE, sample_time_ms


class SteerAngleNode(Node):
    def __init__(self):
        super().__init__('steer_angle_node')

        self.declare_parameter('bind', config.STEER_ANGLE_BIND)
        self.declare_parameter('port', config.STEER_ANGLE_PORT)
        self.declare_parameter('board_ip', config.STEER_IP)
        self.declare_parameter('board_port', config.STEER_SRC_PORT)
        self.declare_parameter('sign', config.STEER_ANGLE_SIGN)
        self.declare_parameter('timeout_sec', config.STEER_ANGLE_TIMEOUT_SEC)
        self.declare_parameter('feedback_topic', config.STEERING_FEEDBACK_TOPIC)

        bind = self.get_parameter('bind').value
        port = self.get_parameter('port').value
        # 조향 보드 IP와 송신 포트(5000)가 모두 일치하는 패킷만 받는다.
        self._source = (
            self.get_parameter('board_ip').value,
            self.get_parameter('board_port').value,
        )
        self._sign = self.get_parameter('sign').value
        self._timeout = self.get_parameter('timeout_sec').value
        if self._sign not in (-1, 1):
            raise ValueError('sign must be -1 or 1')
        self._freshness = FeedbackFreshness(self._timeout)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((bind, port))
        self._sock.setblocking(False)

        self._feedback_pub = self.create_publisher(
            SteeringFeedback, self.get_parameter('feedback_topic').value, 10)

        self._last_feedback = SteeringFeedback()
        self._reported_timeout = False

        # 50Hz 피드백이라 100Hz로 소켓을 비우며 쌓인 패킷을 모두 처리한다.
        self.create_timer(0.01, self._poll)

        self.get_logger().info(
            f'steer_angle 노드 시작 - {bind}:{port} 수신 '
            f'(board={self._source[0]}:{self._source[1]}), '
            f"'{self.get_parameter('feedback_topic').value}' 발행"
        )

    def _poll(self) -> None:
        while True:
            try:
                data, source = self._sock.recvfrom(2048)
            except BlockingIOError:
                break
            if source != self._source:
                continue
            try:
                angle_deg, sample_time_ms = decode_packet(data)
            except ValueError as error:
                self.get_logger().warn(
                    f'Ignored malformed packet: {error}', throttle_duration_sec=1.0)
                continue

            now = time.monotonic()
            previous_ms = self._freshness.last_mcu_ms
            if self._freshness.observe(sample_time_ms, now):
                self.get_logger().warn(
                    f'MCU time went back {previous_ms} -> {sample_time_ms} ms: '
                    'steer board reboot suspected (0° reference may have reset)',
                    throttle_duration_sec=1.0)

            valid = self._freshness.fresh(now)
            self._last_feedback = SteeringFeedback(
                steer_angle=self._sign * angle_deg,
                steer_angle_mcu_ms=sample_time_ms, steer_angle_valid=valid)
            self._feedback_pub.publish(self._last_feedback)
            if valid:
                self._reported_timeout = False

        if (self._freshness.expired(time.monotonic())
                and not self._reported_timeout):
            self.get_logger().warn(
                f'Steer angle unavailable: no UDP feedback or advancing measurement '
                f'timestamp for '
                f'{self._timeout * 1000:.0f} ms')
            self._last_feedback.steer_angle_valid = False
            self._feedback_pub.publish(self._last_feedback)
            self._reported_timeout = True

    def destroy_node(self):
        self._sock.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = SteerAngleNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
