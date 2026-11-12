#!/usr/bin/env python3
"""
모터 보드의 실제 RPM 텔레메트리를 UDP로 받아 ROS2 토픽으로 발행하는 노드.
이 노드는 수신만 하고 제어 명령은 보내지 않는다.

패킷(8바이트, little-endian '<iI'):
- rpm           : int32, -MOTOR_RPM_LIMIT ~ +MOTOR_RPM_LIMIT
- sample_time_ms: uint32, 마지막 CAN RPM 수신 당시 MCU 부팅 후 ms

/motor_feedback (encoder_motor/msg/MotorFeedback)에 값·MCU 시각·PC 유효성을
함께 발행한다. 기존 5바이트 패킷은 거부한다. UDP 수신 중단 또는 MCU 측정시각
정체 시 마지막 값과 시각을 유지한 채 valid=false를 한 번 발행한다.
MCU의 CAN 무효 상태를 직접 받지는 않는다. 펌웨어는 CAN 무효 시 송신을
중단하거나 측정시각을 갱신하지 않아야 한다. valid는 센서 건강 상태가 아니다.
"""

import socket
import struct
import time

import rclpy
from rclpy.node import Node
from encoder_motor import config
from encoder_motor.feedback_freshness import FeedbackFreshness
from encoder_motor.msg import MotorFeedback

PACKET = struct.Struct('<iI')


def decode_packet(data: bytes):
    if len(data) != PACKET.size:
        raise ValueError(f'Expected exactly {PACKET.size} bytes, got {len(data)}')
    rpm, sample_time_ms = PACKET.unpack(data)
    if not -config.MOTOR_RPM_LIMIT <= rpm <= config.MOTOR_RPM_LIMIT:
        raise ValueError(f'RPM {rpm} outside controller protocol range')
    return rpm, sample_time_ms


class MotorRpmNode(Node):
    def __init__(self):
        super().__init__('motor_rpm_node')

        self.declare_parameter('bind', config.MOTOR_RPM_BIND)
        self.declare_parameter('port', config.MOTOR_RPM_PORT)
        self.declare_parameter('board_ip', config.MOTOR_IP)
        self.declare_parameter('timeout_sec', config.MOTOR_RPM_TIMEOUT_SEC)
        self.declare_parameter('feedback_topic', config.MOTOR_FEEDBACK_TOPIC)

        bind = self.get_parameter('bind').value
        port = self.get_parameter('port').value
        # 원본 수신 스크립트와 같이 보드 IP와 송신 포트까지 일치하는 패킷만 받는다.
        self._source = (self.get_parameter('board_ip').value, port)
        self._timeout = self.get_parameter('timeout_sec').value
        self._freshness = FeedbackFreshness(self._timeout)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((bind, port))
        self._sock.setblocking(False)

        self._feedback_pub = self.create_publisher(
            MotorFeedback, self.get_parameter('feedback_topic').value, 10)

        self._last_feedback = MotorFeedback()
        self._reported_timeout = False

        # 소켓을 100Hz로 비우며 쌓인 패킷을 모두 처리한다.
        self.create_timer(0.01, self._poll)

        self.get_logger().info(
            f'motor_rpm 노드 시작 - {bind}:{port} 수신 (board={self._source[0]}), '
            f"'{self.get_parameter('feedback_topic').value}' 발행 (<iI, 8 bytes)"
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
                rpm, sample_time_ms = decode_packet(data)
            except ValueError as error:
                self.get_logger().warn(
                    f'Ignored malformed packet: {error}', throttle_duration_sec=1.0)
                continue

            now = time.monotonic()
            previous_ms = self._freshness.last_mcu_ms
            if self._freshness.observe(sample_time_ms, now):
                self.get_logger().warn(
                    f'MCU time went back {previous_ms} -> {sample_time_ms} ms: '
                    'motor board reboot or packet reordering suspected',
                    throttle_duration_sec=1.0)
            valid = self._freshness.fresh(now)
            self._last_feedback = MotorFeedback(
                motor_rpm=rpm, motor_rpm_mcu_ms=sample_time_ms,
                motor_rpm_valid=valid)
            self._feedback_pub.publish(self._last_feedback)
            if valid:
                self._reported_timeout = False

        if (self._freshness.expired(time.monotonic())
                and not self._reported_timeout):
            self.get_logger().warn(
                f'RPM unavailable: no UDP telemetry or advancing measurement '
                f'timestamp for {self._timeout * 1000:.0f} ms')
            self._last_feedback.motor_rpm_valid = False
            self._feedback_pub.publish(self._last_feedback)
            self._reported_timeout = True

    def destroy_node(self):
        self._sock.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = MotorRpmNode()
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
