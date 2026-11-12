"""Shared viewer payload budget: 250 kB/s, one 32 kB burst (<901 MB/hour).

TCP, SSH and retransmission need the remaining headroom. Not a carrier meter.
"""
import asyncio
from collections import deque
import time


class ViewerBudget:
    def __init__(self, rate=250_000, burst=32_000):
        self.rate, self.burst = rate, burst
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.history = deque()
        self.total = 0
        self.lock = asyncio.Lock()
        self.waited = 0
        self.priority_waiters = 0

    async def acquire(self, size, *, priority=False):
        if priority: self.priority_waiters += 1
        try:
            await self._acquire(size, priority)
        finally:
            if priority: self.priority_waiters -= 1

    async def _acquire(self, size, priority):
        remaining = size
        while remaining:
            part = min(remaining, self.burst)
            while True:
                async with self.lock:
                    now = time.monotonic()
                    self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
                    self.updated = now
                    if self.tokens >= part and (priority or not self.priority_waiters):
                        self.tokens -= part; self.total += part
                        while self.history and self.history[0][0] <= now - 3600:
                            self.history.popleft()
                        second = int(now)
                        if self.history and self.history[-1][0] == second:
                            self.history[-1][1] += part
                        else: self.history.append([second, part])
                        break
                    delay = max(.002, (part - self.tokens) / self.rate)
                self.waited += 1
                await asyncio.sleep(max(.001, delay))
            remaining -= part

    def snapshot(self):
        now = time.monotonic()
        while self.history and self.history[0][0] <= now - 3600:
            self.history.popleft()
        return {'limit_bytes_s': self.rate, 'hour_payload_limit': self.rate * 3600 + self.burst,
                'last_hour_bytes': sum(n for _, n in self.history), 'total_bytes': self.total,
                'waits': self.waited, 'priority_waiters': self.priority_waiters}
