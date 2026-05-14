from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass
class LimitRule:
    max_requests: int
    window_seconds: int = 60


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, rule: LimitRule) -> tuple[bool, int]:
        now = time.time()
        cutoff = now - max(1, int(rule.window_seconds))
        with self._lock:
            bucket = self._events.get(key)
            if bucket is None:
                bucket = deque()
                self._events[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= max(1, int(rule.max_requests)):
                retry_after = int(max(1, round(bucket[0] + rule.window_seconds - now)))
                return False, retry_after
            bucket.append(now)
            return True, 0

