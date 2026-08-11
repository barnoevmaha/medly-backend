"""Per-user request ceilings for the paid AI path.

An in-process sliding window. That is the honest scope: it is per worker, so
two workers allow two windows, and it resets on restart. For a single-container
deployment it is exactly right, and it is the difference between a stuck send
button and a surprise invoice. Swap the store for Redis if the API is ever
scaled horizontally — the interface below would not change.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Tuple


@dataclass(frozen=True)
class RateVerdict:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowLimiter:
    def __init__(self, per_minute: int, per_hour: int) -> None:
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, hits: Deque[float], now: float) -> None:
        while hits and now - hits[0] > 3600:
            hits.popleft()

    def check(self, key: str) -> RateVerdict:
        """Would a request right now be allowed? Records it if so."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            self._prune(hits, now)

            in_last_minute = sum(1 for hit in hits if now - hit <= 60)
            if in_last_minute >= self.per_minute:
                oldest_recent = next(hit for hit in hits if now - hit <= 60)
                return RateVerdict(False, max(1, int(60 - (now - oldest_recent))))

            if len(hits) >= self.per_hour:
                return RateVerdict(False, max(1, int(3600 - (now - hits[0]))))

            hits.append(now)
            return RateVerdict(True)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


class InFlightGuard:
    """Stops the same user having two AI calls running at once.

    Cheap protection against a double-tapped send button and against one
    account fanning out parallel requests into the shared quota.
    """

    def __init__(self) -> None:
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def acquire(self, key: str) -> bool:
        with self._lock:
            if key in self._active:
                return False
            self._active.add(key)
            return True

    def release(self, key: str) -> None:
        with self._lock:
            self._active.discard(key)


def build(per_minute: int, per_hour: int) -> Tuple[SlidingWindowLimiter, InFlightGuard]:
    return SlidingWindowLimiter(per_minute, per_hour), InFlightGuard()
