"""A small in-memory sliding-window rate limiter (one process; enough for the demo)."""

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 3600.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Count one request for `key`; False when the limit for the window is used up."""
        if self.limit <= 0:
            return True
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # forget idle clients
                for idle in [k for k, v in self._hits.items() if not v]:
                    del self._hits[idle]
            return True
