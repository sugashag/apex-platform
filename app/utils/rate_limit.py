"""Simple in-memory IP-based rate limiter.

Sized for single-process dev/test + small production deployments. A real
multi-instance deployment should swap this for Redis (e.g. via the existing
REDIS_URL); the interface (``hit(key)``) is intentionally tiny so the swap
is a one-file change.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Iterable


class InMemoryRateLimiter:
    """Sliding-window counter keyed by (caller_ip, bucket_name)."""

    def __init__(self, *, max_hits: int, window_seconds: int = 60) -> None:
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Record a request. Return True if allowed, False if over-limit."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_hits:
                return False
            bucket.append(now)
            return True

    def reset(self, keys: Iterable[str] | None = None) -> None:
        """Drop buckets — used by tests that need a clean slate."""
        with self._lock:
            if keys is None:
                self._buckets.clear()
            else:
                for k in keys:
                    self._buckets.pop(k, None)
