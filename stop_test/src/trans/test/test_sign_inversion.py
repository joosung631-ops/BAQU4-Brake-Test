"""Check signed conversions and the actual callback's bytes without hardware UDP."""
import contextlib
import io
import math
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trans import motor, steer


class ConversionTests(unittest.TestCase):
    def test_signed_fractional_values_and_clipping(self):
        cases = [(-2., 17.01, 891.387), (-1., 17.01, 891.387), (-.5, 8.505, 445.6935),
                 (-.025, .42525, 22.284675), (0., 0., 0.), (.025, -.42525, -22.284675),
                 (.5, -8.505, -445.6935), (1., -17.01, -891.387), (2., -17.01, -891.387)]
        for raw, angle, speed in cases:
            with self.subTest(raw=raw):
                self.assertAlmostEqual(steer.to_deg(raw), angle)
                self.assertAlmostEqual(motor.to_speed_raw(raw), speed)

    def test_nonfinite_commands_are_rejected(self):
        for convert in (steer.to_deg, motor.to_speed_raw):
            for raw in (math.nan, math.inf, -math.inf):
                with self.subTest(convert=convert, raw=raw):
                    with self.assertRaises(ValueError):
                        convert(raw)


class PacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import rclpy
        rclpy.init(args=['--ros-args', '-p', 'cmd_topic:=/trans/sign_test/cmd',
                        '-p', 'command_events_topic:=/trans/sign_test/events'])

    @classmethod
    def tearDownClass(cls):
        import rclpy
        rclpy.shutdown()

    def setUp(self):
        from trans.trans_node import TransNode
        with patch('trans.trans_node.socket.socket') as socket_factory:
            self.node = TransNode()
        self.socket = socket_factory.return_value
        self.events = Mock()
        self.node._event_pub = self.events
        self.node._test_mode = False

    def tearDown(self):
        self.node.destroy_node()

    def send(self, values):
        from std_msgs.msg import Float32MultiArray
        message = Float32MultiArray(data=values)
        with contextlib.redirect_stdout(io.StringIO()):
            self.node._on_cmd(message)
        return message

    def test_all_destinations_receive_same_inverted_float32_packet(self):
        for raw in (-2., -1., -.025, 0., .025, .5, 1., 2.):
            for braking in (0., 1.):
                with self.subTest(raw=raw, braking=braking):
                    self.socket.reset_mock()
                    message = self.send([raw, raw, braking])
                    calls = self.socket.sendto.call_args_list
                    self.assertEqual(len(calls), 3)
                    expected = struct.pack('<ffB',
                        max(-17.01, min(17.01, -message.data[0]*17.01)),
                        max(-891.387, min(891.387, -message.data[1]*891.387)),
                        0x80 if braking else 0)
                    for call, address in zip(calls, self.node._addrs):
                        self.assertEqual(call.args, (expected, address))
                        self.assertEqual(len(call.args[0]), 9)
                    event = self.events.publish.call_args.args[0]
                    self.assertEqual(event.steering_raw, message.data[0])
                    self.assertEqual(event.speed_raw, message.data[1])
                    self.assertEqual(event.brake, bool(braking))

    def test_dry_run_publishes_observation_without_udp(self):
        from vehicle_recorder.msg import CommandEvent
        self.node._test_mode = True
        self.send([.5, .2, 1.])
        self.socket.sendto.assert_not_called()
        self.assertEqual(self.events.publish.call_args.args[0].stage, CommandEvent.DRY_RUN)

    def test_nonfinite_commands_send_no_packet(self):
        for values in ([math.nan, 0., 0.], [0., math.inf, 0.]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self.send(values)
                self.socket.sendto.assert_not_called()
                self.events.publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
