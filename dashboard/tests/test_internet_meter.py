import ipaddress
import json
from pathlib import Path
import tempfile
import unittest

from dashboard.internet_meter import connected_networks, internet_bytes
from dashboard.traffic import TrafficMonitor


def packet(src, dst, size=1200):
    source, target = ipaddress.ip_address(src), ipaddress.ip_address(dst)
    if source.version == 4:
        header = bytearray(20)
        header[0] = 0x45
        header[2:4] = size.to_bytes(2, 'big')
        header[12:16], header[16:20] = source.packed, target.packed
    else:
        header = bytearray(40)
        header[0] = 0x60
        header[4:6] = (size - 40).to_bytes(2, 'big')
        header[8:24], header[24:40] = source.packed, target.packed
    return bytes(header)


class InternetMeterTests(unittest.TestCase):
    def test_upload_download_and_tunnel_outer_ip_count_once(self):
        self.assertEqual(internet_bytes(packet('192.168.43.108', '8.8.8.8'), True), 1200)
        self.assertEqual(internet_bytes(packet('8.8.8.8', '192.168.43.108'), False), 1200)
        self.assertEqual(internet_bytes(packet('100.99.1.1', '100.99.1.2'), True), 0)

    def test_lan_broadcast_ros_multicast_and_phone_dns_are_excluded(self):
        for peer in ['192.168.43.1', '192.168.0.164', '10.0.0.2', '172.18.0.3',
                     '239.255.0.1', '255.255.255.255', '169.254.1.1', '127.0.0.1']:
            with self.subTest(peer=peer):
                self.assertEqual(internet_bytes(packet('192.168.43.108', peer), True), 0)
                self.assertEqual(internet_bytes(packet(peer, '192.168.43.108'), False), 0)

    def test_ipv6_internet_and_local_addresses(self):
        local = '2001:4860:1234::1'
        self.assertEqual(internet_bytes(packet(local, '2606:4700:4700::1111'), True), 1200)
        self.assertEqual(internet_bytes(packet('2606:4700:4700::1111', local), False), 1200)
        for peer in ['fe80::1', 'fd7a:115c:a1e0::1', 'ff02::1', '::1']:
            self.assertEqual(internet_bytes(packet(local, peer), True), 0)
        onlink = [ipaddress.ip_network('2001:4860:1234::/64')]
        self.assertEqual(internet_bytes(packet(local, '2001:4860:1234::2'), True, onlink), 0)

    def test_connected_route_parsing_and_global_lan_exclusion(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'route').write_text('header\nwifi 0000A8C0 00000000 0001 0 0 0 00FFFFFF\n')
            (root / 'ipv6_route').write_text(
                '20014860123400000000000000000000 40 ' + '0'*32 + ' 00 ' + '0'*32 +
                ' 00000100 0 0 00000001 wifi\n')
            networks = connected_networks('wifi', root)
            self.assertIn(ipaddress.ip_network('192.168.0.0/24'), networks)
            self.assertIn(ipaddress.ip_network('2001:4860:1234::/64'), networks)
        self.assertEqual(internet_bytes(packet('8.8.8.1', '8.8.8.8'), True,
                                       [ipaddress.ip_network('8.8.8.0/24')]), 0)

    def test_truncated_invalid_and_non_ip_headers(self):
        for data in [b'', b'\x45', bytes(60), b'\x60'*20, bytes([0x41])+bytes(59)]:
            self.assertEqual(internet_bytes(data, True), 0)
        # A header-only snapshot still counts the entire declared IP packet.
        self.assertEqual(internet_bytes(packet('192.168.43.108', '1.1.1.1', 1500), True), 1500)

    def test_fresh_totals_stale_missing_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'internet.json'
            monitor = TrafficMonitor(internet_path=path)
            self.assertIsNotNone(monitor.sample_internet(1)['error'])
            def report(now, rx, tx, session='a', error=None):
                path.write_text(json.dumps(dict(session=session, monotonic=now,
                                               received=rx, sent=tx, interfaces=['wifi'], error=error)))
            report(1, 1000, 2000)
            self.assertEqual(monitor.sample_internet(1)['total'], 0)
            report(2, 1600, 2400)
            result = monitor.sample_internet(2)
            self.assertEqual(result['total'], 1000)
            self.assertEqual(result['per_second'], 1000)
            self.assertEqual(result['measurement'], 'internet_ip_estimate')
            self.assertIsNone(monitor.sample_internet(8)['per_second'])
            report(9, 999999, 999999, 'b')
            self.assertEqual(monitor.sample_internet(9)['total'], 1000)
            report(10, 1000000, 1000000, 'b', 'capture dropped')
            self.assertEqual(monitor.sample_internet(10)['error'], 'capture dropped')


if __name__ == '__main__':
    unittest.main()
