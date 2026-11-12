"""Validate local collector reports and expire data when ROS stops."""

import math
import time


class TopicStore:
    ACTIVE_SECONDS = 3.0

    def __init__(self):
        self.topics = []
        self.received_at = None

    def update(self, payload, now=None):
        if not isinstance(payload, dict) or not isinstance(payload.get("topics"), list):
            raise ValueError("topics must be a list")
        if len(payload["topics"]) > 1024:
            raise ValueError("too many topics")
        validated = []
        names = set()
        for row in payload["topics"]:
            if not isinstance(row, dict):
                raise ValueError("invalid topic")
            name, hz, age = row.get("name"), row.get("hz"), row.get("age")
            retained = row.get("retained", False)
            if type(retained) is not bool:
                raise ValueError("invalid retention flag")
            if not isinstance(name, str) or not name.startswith("/") or len(name) > 256 or name in names:
                raise ValueError("invalid topic name")
            for value in ([age] if hz is None else [hz, age]):
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError("invalid topic statistics")
            names.add(name)
            validated.append({"name": name, "hz": hz, "age": age, "retained": retained})
        self.topics = sorted((row for row in validated if not row["name"].startswith(("/lidar/", "/ouster/"))), key=lambda row: row["name"])
        self.received_at = time.monotonic() if now is None else now

    def snapshot(self, now=None):
        if self.received_at is None:
            return []
        elapsed = (time.monotonic() if now is None else now) - self.received_at
        if elapsed >= self.ACTIVE_SECONDS:
            return []
        result = []
        for row in self.topics:
            fresh = row["age"] + elapsed < self.ACTIVE_SECONDS
            if row["retained"] or fresh:
                result.append({"name": row["name"], "hz": row["hz"] if fresh else None,
                               "retained": row["retained"]})
        return result
