import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard.traffic import BrowserTraffic, TrafficCounter, TrafficMonitor, default_interfaces, read_counters


class TrafficTests(unittest.TestCase):
    def test_rates_use_elapsed_time_and_both_directions(self):
        counter = TrafficCounter()
        counter.sample({"wifi": (10_000, 20_000)}, ["wifi"], 100)
        result = counter.sample({"wifi": (10_600, 20_400)}, ["wifi"], 102)
        self.assertEqual(result["total"], 1000)
        self.assertEqual(result["per_second"], 500)
        self.assertEqual(result["per_hour"], 1_800_000)

    def test_hourly_averages_available_rates_before_ten_samples(self):
        counter = TrafficCounter()
        initial = counter.sample({"wifi": (0, 0)}, ["wifi"], 100)
        self.assertEqual(initial["per_hour"], 0)
        counter.sample({"wifi": (600, 400)}, ["wifi"], 102)
        idle = counter.sample({"wifi": (600, 400)}, ["wifi"], 110)
        self.assertEqual(idle["per_second"], 0)
        self.assertEqual(idle["per_hour"], 900_000)  # mean(500, 0) * 3600
        burst = counter.sample({"wifi": (1200, 800)}, ["wifi"], 111)
        self.assertEqual(burst["per_second"], 1000)
        self.assertEqual(burst["per_hour"], 1_800_000)  # mean(500, 0, 1000) * 3600

    def test_camera_burst_leaves_hourly_estimate_after_ten_idle_samples(self):
        counter = TrafficCounter()
        counter.sample({'wifi': (0, 0)}, ['wifi'], 0)
        for second in range(1, 11):
            result = counter.sample({'wifi': (0, second * 1000)}, ['wifi'], second)
        self.assertEqual(result['per_hour'], 3_600_000)
        for idle_second in range(1, 11):
            result = counter.sample({'wifi': (0, 10000)}, ['wifi'], 10 + idle_second)
            self.assertEqual(result['per_second'], 0)
            self.assertEqual(result['per_hour'], (10 - idle_second) * 100 * 3600)
            self.assertEqual(result['total'], 10000)

    def test_smoothing_resize_preserves_totals_and_uses_newest_samples(self):
        counter = TrafficCounter()
        counter.sample({'wifi': (0, 0)}, ['wifi'], 0)
        for second, total in enumerate((100, 300, 600), 1):
            counter.sample({'wifi': (0, total)}, ['wifi'], second)
        counter.set_smoothing_samples(2)
        self.assertEqual(list(counter.recent_rates), [200, 300])
        counter.set_smoothing_samples(1)
        result = counter.sample({'wifi': (0, 600)}, ['wifi'], 4)
        self.assertEqual(result['total'], 600)
        self.assertEqual(result['per_hour'], 0)
        counter.set_smoothing_samples(3)
        result = counter.sample({'wifi': (0, 1200)}, ['wifi'], 5)
        self.assertEqual(result['total'], 1200)
        self.assertEqual(result['per_hour'], 300 * 3600)  # Available rates: 0, 600.
        counter.set_smoothing_samples(3)
        self.assertEqual(list(counter.recent_rates), [0, 600])

    def test_duration_uses_monotonic_clock_and_survives_wall_clock_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            monitor = TrafficMonitor(host_root=root)
            with patch("dashboard.traffic.time.monotonic", side_effect=[100, 3765]), \
                 patch("dashboard.traffic.time.time", side_effect=[1700000000, 1600000000]):
                first = monitor.sample()
                later = monitor.sample()
            self.assertEqual(first["elapsed_seconds"], 0)
            self.assertEqual(later["elapsed_seconds"], 3665)
            self.assertEqual(later["started_at"], first["started_at"])

    def test_reset_disconnect_and_interface_change_do_not_inflate_totals(self):
        counter = TrafficCounter()
        counter.sample({"wifi": (1000, 1000)}, ["wifi"], 1)
        counter.sample({"wifi": (1100, 1100)}, ["wifi"], 2)
        reset = counter.sample({"wifi": (10, 10)}, ["wifi"], 3)
        self.assertEqual(reset["total"], 200)
        self.assertEqual(reset["per_hour"], 0)
        disconnected = counter.sample({}, [], 4)
        self.assertIsNone(disconnected["per_second"])
        self.assertTrue(disconnected["error"])
        result = counter.sample({"usb": (999999, 999999)}, ["usb"], 5)
        self.assertEqual(result["total"], 200)
        self.assertEqual(result["per_second"], 0)
        self.assertEqual(result["per_hour"], 0)

    def test_route_selection_deduplicates_ipv4_ipv6_and_ignores_nondefaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "route").write_text(
                "Iface Destination Gateway Flags RefCnt Use Metric Mask\n"
                "wifi 00000000 01000000 0003 0 0 600 00000000\n"
                "ethernet 00000000 01000000 0003 0 0 900 00000000\n"
                "lidar 0000A8C0 00000000 0001 0 0 0 00FFFFFF\n"
            )
            zero = "0" * 32
            (root / "ipv6_route").write_text(
                f"{zero} 00 {zero} 00 {zero} 00000258 0 0 00000003 wifi\n"
                f"{zero} 00 {zero} 00 {zero} ffffffff 0 0 00200200 lo\n"
            )
            self.assertEqual(default_interfaces(root), ["wifi"])

    def test_parse_and_monitor_keep_host_failure_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dev").write_text(
                "header\nheader\n"
                "eth0: 100 1 0 0 0 0 0 0 200 1 0 0 0 0 0 0\n"
                "lo: 9999 1 0 0 0 0 0 0 9999 1 0 0 0 0 0 0\n"
            )
            self.assertEqual(read_counters(root / "dev")["eth0"], (100, 200))
            monitor = TrafficMonitor(host_root=root / "missing")
            result = monitor.sample()
            self.assertIsNotNone(result["host"]["error"])
            self.assertIsNone(result["dashboard"]["error"])
            self.assertEqual(result["dashboard"]["interfaces"], ["browser"])
            pinned = TrafficMonitor(host_root=root, uplink="eth0")
            self.assertIsNone(pinned.sample()["host"]["error"])

    # 이전 전체 인터페이스 합산 검증(현재 요구와 달라 비활성화):
    #     def test_total_includes_local_traffic_without_default_route(self):
    #         with tempfile.TemporaryDirectory() as directory:
    #             root = Path(directory)
    #             def counters(lo, bridge, wifi):
    #                 (root / 'dev').write_text('header\nheader\n' + ''.join(
    #                     f'{name}: {rx} 0 0 0 0 0 0 0 {tx} 0 0 0 0 0 0 0\n'
    #                     for name, (rx, tx) in [('lo', lo), ('br-test', bridge), ('wifi', wifi)]))
    #             counters((100, 100), (200, 200), (500, 500))
    #             meter = BrowserTraffic()
    #             monitor = TrafficMonitor(host_root=root, browser=meter, uplink='wifi')
    #             with patch('dashboard.traffic.time.monotonic', side_effect=[1, 2, 3]):
    #                 monitor.sample()
    #                 counters((1100, 1100), (1200, 1200), (500, 500))
    #                 meter.sent = 800
    #                 result = monitor.sample()
    #                 self.assertEqual(result['host']['total'], 4000)
    #                 self.assertEqual(result['dashboard']['total'], 800)
    #                 self.assertEqual(result['host']['interfaces'], ['br-test', 'lo', 'wifi'])
    #                 for key in ('total', 'per_second', 'per_hour'):
    #                     self.assertGreaterEqual(result['host'][key], result['dashboard'][key])
    #                 idle = monitor.sample()
    #                 for key in ('total', 'per_second', 'per_hour'):
    #                     self.assertGreaterEqual(idle['host'][key], idle['dashboard'][key])
    # 
    def test_hotspot_excludes_local_and_docker_traffic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def counters(lo, bridge, wifi):
                (root / 'dev').write_text('header\nheader\n' + ''.join(
                    f'{name}: {rx} 0 0 0 0 0 0 0 {tx} 0 0 0 0 0 0 0\n'
                    for name, (rx, tx) in [('lo', lo), ('br-test', bridge), ('wifi', wifi)]))
            counters((100, 100), (200, 200), (500, 500))
            meter = BrowserTraffic()
            monitor = TrafficMonitor(host_root=root, browser=meter, uplink='wifi')
            with patch('dashboard.traffic.time.monotonic', side_effect=[1, 2, 3]):
                monitor.sample()
                counters((1000000, 1000000), (2000000, 2000000), (500, 500))
                meter.sent = 800000
                local = monitor.sample()
                for scope in ('host', 'dashboard'):
                    for key in ('total', 'per_second', 'per_hour'):
                        self.assertEqual(local[scope][key], 0)
                counters((1000000, 1000000), (2000000, 2000000), (1500, 1500))
                meter.internet_sent = 800
                remote = monitor.sample()
                self.assertEqual(remote['host']['total'], 2000)
                self.assertEqual(remote['dashboard']['total'], 800)
                self.assertEqual(remote['host']['interfaces'], ['wifi'])

    def test_new_virtual_link_does_not_count_lifetime_or_reset_stable_average(self):
        c = TrafficCounter()
        c.sample({'lo': (0, 0)}, ['lo'], 1)
        c.sample({'lo': (1000, 1000)}, ['lo'], 2)
        result = c.sample({'lo': (2000, 2000), 'veth-new': (9999999, 9999999)},
                          ['lo', 'veth-new'], 3)
        self.assertEqual(result['total'], 4000)
        self.assertEqual(result['per_second'], 2000)
        self.assertEqual(result['per_hour'], 7200000)

    def test_browser_totals_rates_and_smoothed_hourly_estimate(self):
        meter = BrowserTraffic()
        with tempfile.TemporaryDirectory() as directory:
            monitor = TrafficMonitor(host_root=Path(directory), browser=meter)
            with patch('dashboard.traffic.time.monotonic', side_effect=[100, 102, 110]):
                monitor.sample()
                meter.sent += 999_996
                meter.received += 4
                meter.internet_sent += 999_996
                meter.internet_received += 4
                active = monitor.sample()['dashboard']
                idle = monitor.sample()['dashboard']
        self.assertEqual(active['total'], 1_000_000)
        self.assertEqual(active['per_second'], 500_000)
        self.assertEqual(active['per_hour'], 1_800_000_000)
        self.assertEqual(idle['total'], 1_000_000)
        self.assertEqual(idle['per_second'], 0)
        self.assertEqual(idle['per_hour'], 900_000_000)


if __name__ == "__main__":
    unittest.main()
