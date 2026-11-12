#!/usr/bin/env python3
"""Integration test in an isolated Humble container; only loopback UDP is sent."""

import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import time
import unittest

import rclpy
from encoder_motor.feedback_freshness import FeedbackFreshness, mcu_time_went_back
from encoder_motor.msg import MotorFeedback, SteeringFeedback
from rclpy.node import Node


class FeedbackTransportTest(unittest.TestCase):
    def test_freshness(self):
        tracker = FeedbackFreshness(0.1)
        start = tracker.started
        self.assertFalse(tracker.fresh(start))
        self.assertTrue(tracker.expired(start + 0.11))
        self.assertFalse(tracker.observe(0, start))  # tick=0 is a valid sample
        self.assertTrue(tracker.fresh(start))
        tracker.observe(0, start + 0.09)
        self.assertFalse(tracker.fresh(start + 0.11))  # repeats cannot renew age
        tracker.observe(20, start + 0.12)
        self.assertTrue(tracker.fresh(start + 0.12))
        self.assertFalse(mcu_time_went_back(0xFFFFFFF0, 10))
        self.assertTrue(mcu_time_went_back(100, 5))
        for bad in (0.0, -1.0, math.nan, math.inf):
            with self.assertRaises(ValueError):
                FeedbackFreshness(bad)

    def test_loopback_nodes(self):
        rclpy.init()
        node = Node('feedback_transport_test')
        received = {'motor': [], 'steering': []}
        subscriptions = [
            node.create_subscription(MotorFeedback, '/motor_feedback',
                                     received['motor'].append, 100),
            node.create_subscription(SteeringFeedback, '/steering_feedback',
                                     received['steering'].append, 100),
        ]
        out = Path(os.environ.get('TEST_OUTPUT', '/tmp/encoder-feedback-test'))
        out.mkdir(parents=True, exist_ok=True)
        processes, files, sockets = [], [], []

        def pump(seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.005)

        def wait_until(predicate, label, seconds=5):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if predicate():
                    return
                rclpy.spin_once(node, timeout_sec=0.01)
            self.fail(label)

        def board(port, address='127.0.0.2'):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((address, port))
            sockets.append(sock)
            return sock

        try:
            for executable in ('motor_rpm', 'steer_angle'):
                log = (out / f'{executable}.log').open('w')
                files.append(log)
                command = ['ros2', 'run', 'encoder_motor', executable, '--ros-args',
                           '-p', 'bind:=127.0.0.1', '-p', 'board_ip:=127.0.0.2']
                if executable == 'steer_angle':
                    command += ['-p', 'sign:=-1']  # retain configurable angle polarity
                processes.append(subprocess.Popen(command, stdout=log, stderr=log))
            wait_until(lambda: all(node.count_publishers(t) == 1 for t in
                                   ('/motor_feedback', '/steering_feedback')),
                       'both feedback publishers must be discoverable')
            motor, steering = board(5001), board(5000)
            destination_motor, destination_steering = ('127.0.0.1', 5001), ('127.0.0.1', 5002)

            # Board packets at 20 Hz / 50 Hz. Every message must carry its own
            # value and sample tick atomically; same RPM with new ticks is valid.
            start, next_motor, next_steering = time.monotonic(), 0.0, 0.0
            motor_tick, steering_tick = 1000, 1000
            while time.monotonic() - start < 1.0:
                elapsed = time.monotonic() - start
                if elapsed >= next_motor:
                    motor.sendto(struct.pack('<iI', -1200, motor_tick), destination_motor)
                    motor_tick += 50
                    next_motor += 0.05
                if elapsed >= next_steering:
                    steering.sendto(struct.pack('<hI', 1234, steering_tick), destination_steering)
                    steering_tick += 20
                    next_steering += 0.02
                rclpy.spin_once(node, timeout_sec=0.002)
            pump(0.03)
            good_motor = [m for m in received['motor'] if m.motor_rpm_valid]
            good_steering = [m for m in received['steering'] if m.steer_angle_valid]
            self.assertGreaterEqual(len(good_motor), 10)
            self.assertGreaterEqual(len(good_steering), 25)
            self.assertTrue(all(m.motor_rpm == -1200 and
                                (m.motor_rpm_mcu_ms - 1000) % 50 == 0 for m in good_motor))
            self.assertTrue(all(abs(m.steer_angle + 12.34) < 1e-4 and
                                (m.steer_angle_mcu_ms - 1000) % 20 == 0 for m in good_steering))

            topics = dict(node.get_topic_names_and_types())
            self.assertEqual(topics['/motor_feedback'], ['encoder_motor/msg/MotorFeedback'])
            self.assertEqual(topics['/steering_feedback'], ['encoder_motor/msg/SteeringFeedback'])
            for old in ('/motor_rpm', '/motor_rpm_valid', '/steer_angle',
                        '/steer_angle_mcu_ms', '/steer_angle_valid'):
                self.assertNotIn(old, topics)

            # Receive gaps invalidate while retaining the last observed value/tick.
            pump(0.6)
            self.assertFalse(received['motor'][-1].motor_rpm_valid)
            self.assertEqual(received['motor'][-1].motor_rpm, -1200)
            self.assertEqual(received['motor'][-1].motor_rpm_mcu_ms,
                             good_motor[-1].motor_rpm_mcu_ms)
            self.assertFalse(received['steering'][-1].steer_angle_valid)
            self.assertEqual(received['steering'][-1].steer_angle_mcu_ms,
                             good_steering[-1].steer_angle_mcu_ms)

            # Old firmware, malformed/range errors and wrong source must be ignored.
            wrong_port, wrong_ip = board(5999), board(5001, '127.0.0.3')
            motor.sendto(struct.pack('<iB', 777, 1), destination_motor)
            motor.sendto(struct.pack('<iI', 40000, motor_tick), destination_motor)
            steering.sendto(b'12345', destination_steering)
            wrong_port.sendto(struct.pack('<iI', 777, motor_tick), destination_motor)
            wrong_port.sendto(struct.pack('<hI', 777, steering_tick), destination_steering)
            wrong_ip.sendto(struct.pack('<iI', 777, motor_tick), destination_motor)
            pump(0.1)
            self.assertFalse(any(m.motor_rpm == 777 or m.motor_rpm == 40000
                                 for m in received['motor']))
            self.assertFalse(any(abs(m.steer_angle + 7.77) < 1e-4
                                 for m in received['steering']))

            # Correct zero and both signed RPM limits, then uint32 rollover.
            for rpm, tick in ((0, 0), (32000, 50), (-32000, 100),
                              (1500, 0xFFFFFFF0), (-1500, 10)):
                motor.sendto(struct.pack('<iI', rpm, tick), destination_motor)
                wait_until(lambda: any(m.motor_rpm == rpm and
                                       m.motor_rpm_mcu_ms == tick and m.motor_rpm_valid
                                       for m in received['motor']), 'motor signed/tick decoding')
            steering.sendto(struct.pack('<hI', -2400, 0xFFFFFFF0), destination_steering)
            pump(0.03)
            steering.sendto(struct.pack('<hI', 2400, 10), destination_steering)
            wait_until(lambda: any(m.steer_angle == -24.0 and m.steer_angle_mcu_ms == 10
                                   and m.steer_angle_valid for m in received['steering']),
                       'steering rollover and polarity')

            # Continuous UDP with an unchanged acquisition tick must expire.
            start = time.monotonic()
            while time.monotonic() - start < 0.65:
                motor.sendto(struct.pack('<iI', -1500, 10), destination_motor)
                steering.sendto(struct.pack('<hI', 2400, 10), destination_steering)
                pump(0.02)
            self.assertFalse(received['motor'][-1].motor_rpm_valid)
            self.assertFalse(received['steering'][-1].steer_angle_valid)

            # Advancing source ticks restore transport validity.
            motor.sendto(struct.pack('<iI', -1500, 60), destination_motor)
            steering.sendto(struct.pack('<hI', 2400, 30), destination_steering)
            wait_until(lambda: received['motor'][-1].motor_rpm_valid and
                       received['motor'][-1].motor_rpm_mcu_ms == 60 and
                       received['steering'][-1].steer_angle_valid and
                       received['steering'][-1].steer_angle_mcu_ms == 30,
                       'fresh samples must recover validity')
            self.assertTrue(all(p.poll() is None for p in processes))
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for sock in sockets:
                sock.close()
            for log in files:
                log.close()
            node.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
