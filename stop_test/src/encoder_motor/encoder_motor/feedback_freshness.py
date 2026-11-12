"""Freshness measured on the PC monotonic clock, without clock synchronization."""

import math
import time


def mcu_time_went_back(prev_ms: int, new_ms: int) -> bool:
    """Allow uint32 rollover; flag backward jumps (e.g. board restart/reordering)."""
    return (new_ms - prev_ms) % (1 << 32) >= (1 << 31)


class FeedbackFreshness:
    def __init__(self, timeout_sec: float):
        if not math.isfinite(timeout_sec) or timeout_sec <= 0:
            raise ValueError('timeout_sec must be finite and positive')
        self.timeout_sec = timeout_sec
        self.started = time.monotonic()
        self.last_mcu_ms = None
        self.last_received = None
        self.last_advanced = None

    def observe(self, mcu_ms: int, now: float) -> bool:
        previous = self.last_mcu_ms
        went_back = previous is not None and mcu_time_went_back(previous, mcu_ms)
        # A backward jump starts a new clock epoch, as before for steering. This
        # only checks transport freshness; it does not verify the new zero angle.
        if previous is None or mcu_ms != previous:
            self.last_advanced = now
        self.last_mcu_ms = mcu_ms
        self.last_received = now
        return went_back

    def fresh(self, now: float) -> bool:
        return (self.last_received is not None
                and now - self.last_received <= self.timeout_sec
                and now - self.last_advanced <= self.timeout_sec)

    def expired(self, now: float) -> bool:
        if self.last_received is None:
            return now - self.started > self.timeout_sec
        return not self.fresh(now)
