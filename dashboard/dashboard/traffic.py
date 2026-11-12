"""Sample internet-counter snapshots; retain legacy interface counters for callers."""

import time
import json
from collections import deque
from pathlib import Path


def read_counters(path: Path) -> dict[str, tuple[int, int]]:
    counters = {}
    for line in path.read_text().splitlines()[2:]:
        name, values = line.split(":", 1)
        fields = values.split()
        counters[name.strip()] = (int(fields[0]), int(fields[8]))
    return counters


def default_interfaces(root: Path) -> list[str]:
    """Select the lowest-metric default per IP family, deduplicating dual stack."""
    families = [[], []]
    for line in (root / "route").read_text().splitlines()[1:]:
        f = line.split()
        if len(f) >= 8 and f[1] == "00000000" and f[7] == "00000000":
            flags = int(f[3], 16)
            if flags & 1 and not flags & 0x200 and f[0] != "lo":
                families[0].append((int(f[6]), f[0]))
    try:
        ipv6 = (root / "ipv6_route").read_text()
    except FileNotFoundError:
        ipv6 = ""
    for line in ipv6.splitlines():
        f = line.split()
        if len(f) == 10 and f[0] == "0" * 32 and f[1] == "00":
            flags = int(f[8], 16)
            if flags & 1 and not flags & 0x200 and f[9] != "lo":
                families[1].append((int(f[5], 16), f[9]))
    selected = set()
    for routes in families:
        if routes:
            metric = min(cost for cost, _ in routes)
            selected.update(name for cost, name in routes if cost == metric)
    return sorted(selected)


class TrafficCounter:
    SMOOTHING_SAMPLES = 10

    def __init__(self):
        self.total = 0
        self.previous = {}
        self.previous_time = None
        self.recent_rates = deque(maxlen=self.SMOOTHING_SAMPLES)

    def set_smoothing_samples(self, samples):
        if type(samples) is not int or not 1 <= samples <= 3600:
            raise ValueError("smoothing_samples must be an integer from 1 to 3600")
        if self.recent_rates.maxlen != samples:
            self.recent_rates = deque(self.recent_rates, maxlen=samples)

    def sample(self, counters, interfaces, now, error=None):
        selected = {name: counters[name] for name in interfaces if name in counters}
        if not interfaces or len(selected) != len(interfaces):
            error = error or "측정할 네트워크 인터페이스가 없습니다."
        delta = 0
        if not error:
            for name, current in selected.items():
                previous = self.previous.get(name)
                # A new/reconnected device establishes a baseline; never count its
                # lifetime traffic as traffic from the current dashboard session.
                if previous is not None and all(c >= p for c, p in zip(current, previous)):
                    delta += sum(c - p for c, p in zip(current, previous))
        elapsed = now - self.previous_time if self.previous_time is not None else 0
        rate = delta / elapsed if elapsed > 0 else 0
        self.total += delta
        # 이전: 가상 인터페이스가 하나만 생겨도 시간당 평균 전체를 초기화했다.
        # continuous = (bool(self.previous) and selected.keys() == self.previous.keys()
        #               and all(all(c >= p for c, p in zip(current, self.previous[name]))
        #                       for name, current in selected.items()))
        common = selected.keys() & self.previous.keys()
        continuous = bool(common) and all(
            all(c >= p for c, p in zip(selected[name], self.previous[name]))
            for name in common)
        if error or not continuous:
            self.recent_rates.clear()
        elif elapsed > 0:
            self.recent_rates.append(rate)
        hourly = sum(self.recent_rates) / len(self.recent_rates) * 3600 if self.recent_rates else 0
        self.previous = selected if not error else {}
        self.previous_time = now
        return {
            "total": self.total,
            "per_second": round(rate, 1) if not error else None,
            "per_hour": round(hourly, 1) if not error else None,
            "interfaces": interfaces,
            "error": error,
        }


class BrowserTraffic:
    """Application bytes exchanged with viewers, excluding internal ROS uploads."""

    def __init__(self):
        self.sent = 0
        self.received = 0
        self.internet_sent = 0
        self.internet_received = 0


class TrafficMonitor:
    def __init__(self, host_root=Path("/host/net"), uplink="", browser=None, internet_path=None):
        self.internet_path = Path(internet_path) if internet_path else None
        self.host_root = host_root
        self.browser = browser if browser is not None else BrowserTraffic()
        # 핫스팟 인터페이스를 지정하거나 기본 인터넷 경로로 자동 선택한다.
        self.uplink = uplink.strip()
        self.host = TrafficCounter()
        self.dashboard = TrafficCounter()
        self.started_at = None
        self.started_monotonic = None

    def set_smoothing_samples(self, samples):
        self.host.set_smoothing_samples(samples)
        self.dashboard.set_smoothing_samples(samples)

    def sample(self):
        now = time.monotonic()
        if self.started_monotonic is None:
            self.started_monotonic = now
            self.started_at = int(time.time())
        result = {"started_at": self.started_at, "elapsed_seconds": now - self.started_monotonic}
        interfaces = []
        # 이전: browser_counters = {"browser": (self.browser.received, self.browser.sent)}
        browser_counters = {"browser": (self.browser.internet_received, self.browser.internet_sent)}
        if self.internet_path is not None:
            result["host"] = self.sample_internet(now)
        else:
            # Legacy interface totals retained for standalone callers/tests only.
            try:
                counters = read_counters(self.host_root / "dev")
                # 이전: 기본 인터넷 인터페이스만 측정해 localhost/Docker를 누락했다.
                # interfaces = [self.uplink] if self.uplink else default_interfaces(self.host_root)
                # 이전 내부 통신 합산(핫스팟 인터넷 사용량이 아니므로 사용하지 않음):
                # interfaces = sorted(counters)
                interfaces = [self.uplink] if self.uplink else default_interfaces(self.host_root)
                result["host"] = self.host.sample(counters, interfaces, now)
            except (OSError, ValueError, IndexError):
                result["host"] = self.host.sample({}, interfaces, now, "네트워크 통계를 읽을 수 없습니다.")
        result["dashboard"] = self.dashboard.sample(
            # 이전: {"browser": (self.browser.received, self.browser.sent)}, ["browser"], now)
            browser_counters, ["browser"], now)
        return result

    def sample_internet(self, now):
        try:
            data = json.loads(self.internet_path.read_text())
            if not 0 <= now - data["monotonic"] <= 5:
                raise ValueError("stale collector")
            key = data["session"]
            values = (data["received"], data["sent"])
            if not all(type(value) is int and value >= 0 for value in values):
                raise ValueError("invalid counters")
            result = self.host.sample({key: values}, [key], now, data.get("error"))
            result["interfaces"] = data["interfaces"]
            result["measurement"] = "internet_ip_estimate"
            return result
        except (OSError, ValueError, KeyError, TypeError):
            # Never silently substitute all Wi-Fi traffic or zero on failure.
            return self.host.sample({}, [], now, "인터넷 사용량 수집기 연결을 확인하세요.")
