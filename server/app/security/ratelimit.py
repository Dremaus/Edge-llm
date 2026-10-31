"""Ograniczanie liczby zapytań i blokada po nieudanych próbach logowania.

Wszystko w pamięci procesu — wystarcza na jedno urządzenie z jednym procesem serwera.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class TokenBucket:
    """Limit zapytań na klucz (np. id urządzenia): `rate` na minutę, zryw do `burst`."""

    def __init__(
        self, rate_per_min: float, burst: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._rate = rate_per_min / 60.0
        self._burst = float(burst)
        self._clock = clock
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            tokens, last = self._state.get(key, (self._burst, now))
            tokens = min(self._burst, tokens + (now - last) * self._rate)
            if tokens < 1.0:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1.0, now)
            if len(self._state) > 10_000:  # ochrona pamięci przed zalewem kluczy
                self._state.clear()
            return True


class FailureLockout:
    """Po `max_failures` nieudanych próbach w oknie `window_s` blokuje klucz na `lockout_s`."""

    def __init__(
        self,
        max_failures: int = 5,
        window_s: float = 300.0,
        lockout_s: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_failures
        self._window = window_s
        self._lockout = lockout_s
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            until = self._blocked_until.get(key)
            if until is None:
                return False
            if self._clock() >= until:
                del self._blocked_until[key]
                return False
            return True

    def record_failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if now - t < self._window]
            recent.append(now)
            if len(recent) >= self._max:
                self._blocked_until[key] = now + self._lockout
                recent = []
            self._failures[key] = recent
            if len(self._failures) > 10_000:
                self._failures.clear()

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
