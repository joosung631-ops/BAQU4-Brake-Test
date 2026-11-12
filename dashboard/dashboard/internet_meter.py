"""Hotspot internet estimate from IP headers, without storing packet contents.

Run inside the dashboard container with host networking and CAP_NET_RAW. Count IP lengths on the
physical uplink once (including outer VPN packets, ACKs and retransmissions).
LAN/special addresses and directly connected networks are excluded. This is
not a carrier billing meter: phone DNS/proxies and offloading can differ.
"""
import ipaddress
import json
import os
from pathlib import Path
import select
import socket
import struct
import sys
import fcntl
import time
import uuid

if __package__:
    from .traffic import default_interfaces
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dashboard.traffic import default_interfaces

ROOT = Path('/proc/net')
OUTPUT = Path(os.environ.get('INTERNET_METER_OUTPUT',
                             str(Path(__file__).resolve().parents[1] / 'runtime/internet.json')))


def connected_networks(interface, root=ROOT):
    networks = []
    for line in (root / 'route').read_text().splitlines()[1:]:
        f = line.split()
        if len(f) >= 8 and f[0] == interface and f[2] == '00000000' and f[7] != '00000000':
            addr = socket.inet_ntoa(struct.pack('<I', int(f[1], 16)))
            mask = socket.inet_ntoa(struct.pack('<I', int(f[7], 16)))
            networks.append(ipaddress.ip_network(f'{addr}/{mask}', strict=False))
    for line in (root / 'ipv6_route').read_text().splitlines():
        f = line.split()
        if len(f) == 10 and f[9] == interface and f[4] == '0' * 32 and f[1] != '00':
            addr = ipaddress.IPv6Address(int(f[0], 16))
            networks.append(ipaddress.ip_network(f'{addr}/{int(f[1], 16)}', strict=False))
    return networks


def internet_bytes(header, outgoing, networks=()):
    """Return declared IP length for a global remote peer, else zero."""
    if not header:
        return 0
    version = header[0] >> 4
    if version == 4 and len(header) >= 20:
        ihl = (header[0] & 15) * 4
        length = int.from_bytes(header[2:4], 'big')
        if ihl < 20 or length < ihl or len(header) < ihl:
            return 0
        peer = ipaddress.ip_address(header[16:20] if outgoing else header[12:16])
    elif version == 6 and len(header) >= 40:
        payload = int.from_bytes(header[4:6], 'big')
        if not payload:  # IPv6 jumbograms are outside this estimate.
            return 0
        length = 40 + payload
        peer = ipaddress.ip_address(header[24:40] if outgoing else header[8:24])
    else:
        return 0
    if not peer.is_global or peer.is_multicast or peer.is_reserved:
        return 0
    if any(peer.version == net.version and peer in net for net in networks):
        return 0
    return length


def main():
    session = uuid.uuid4().hex
    totals = [0, 0]  # receive, send
    sockets = {}
    networks = {}
    dropped = 0
    error = None
    refresh = report = 0
    pinned = os.environ.get('DASHBOARD_UPLINK_INTERFACE', '').strip()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lock = (OUTPUT.parent / 'internet.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('인터넷 사용량 수집기가 이미 실행 중입니다.', flush=True)
        return
    print(f'인터넷 사용량 수집 시작: {OUTPUT} (Ctrl+C로 종료)', flush=True)
    while True:
        now = time.monotonic()
        if now >= refresh:
            refresh = now + 2
            try:
                # Never add the decrypted Tailscale/Docker path a second time.
                desired = [pinned] if pinned else [n for n in default_interfaces(ROOT)
                                                    if (Path('/sys/class/net') / n / 'device').exists()]
                for name in list(sockets):
                    if name not in desired:
                        sockets.pop(name).close()
                        networks.pop(name, None)
                for name in desired:
                    networks[name] = connected_networks(name)
                    if name not in sockets:
                        sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(3))
                        try:
                            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                            sock.bind((name, 0))
                            sock.setblocking(False)
                        except Exception:
                            sock.close()
                            raise
                        sockets[name] = sock
                error = None if desired else '인터넷 연결 인터페이스가 없습니다.'
            except (OSError, ValueError) as exc:
                error = f'인터넷 사용량 수집 오류: {exc}'
        if now >= report:
            report = now + 0.5
            for sock in sockets.values():
                # PACKET_STATISTICS resets the kernel drop counter on read.
                _, lost = struct.unpack('II', sock.getsockopt(263, 6, 8))
                dropped += lost
            snapshot = dict(session=session, monotonic=now, received=totals[0], sent=totals[1],
                            interfaces=sorted(sockets), dropped=dropped,
                            error=error or ('인터넷 계측 패킷 누락: 누적값이 실제보다 작을 수 있습니다.' if dropped else None))
            temporary = OUTPUT.with_suffix('.tmp')
            temporary.write_text(json.dumps(snapshot))
            temporary.replace(OUTPUT)
        ready, _, _ = select.select(list(sockets.values()), [], [], 0.1)
        for sock in ready:
            # Bound each drain so reports remain fresh during sustained load.
            for _ in range(512):
                try:
                    header, address = sock.recvfrom(60)
                except BlockingIOError:
                    break
                name, protocol, kind = address[:3]
                if protocol not in (0x0800, 0x86DD) or kind not in (0, 4):
                    continue
                outgoing = kind == 4
                totals[int(outgoing)] += internet_bytes(header, outgoing, networks.get(name, ()))


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('패킷 계측 권한이 필요합니다. sudo python3 ' + str(Path(__file__).resolve()))
    try:
        main()
    except KeyboardInterrupt:
        print('인터넷 사용량 수집을 종료했습니다.', flush=True)
