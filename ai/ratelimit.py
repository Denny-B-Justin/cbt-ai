"""Pace requests to the provider and retry temporary failures. Provider-neutral."""

from __future__ import annotations

import random
import threading
import time
from typing import Callable, Optional, TypeVar

from .types import AIRateLimitError, AIServerError, Cancelled

T = TypeVar("T")
MAX_ATTEMPTS = 6


def _sleep(seconds: float, cancelled: Optional[Callable[[], bool]] = None) -> None:
    end = time.monotonic() + seconds
    while True:
        if cancelled and cancelled():
            raise Cancelled()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.25, left))


class RateLimiter:
    """Spaces calls at least 60/rpm seconds apart; slows down after a 429 and recovers on success."""

    def __init__(self, rpm: int):
        self.base = 60.0 / max(1, rpm)
        self.penalty = 1.0
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self, cancelled: Optional[Callable[[], bool]] = None) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.base * self.penalty
        if start > now:
            _sleep(start - now, cancelled)

    def slow_down(self) -> None:
        with self._lock:
            self.penalty = min(self.penalty * 1.5, 6.0)

    def speed_up(self) -> None:
        with self._lock:
            self.penalty = max(1.0, self.penalty * 0.9)


def call_with_retries(fn: Callable[[], T], limiter: RateLimiter, cancelled: Optional[Callable[[], bool]] = None) -> T:
    attempt = 0
    while True:
        attempt += 1
        limiter.wait(cancelled)
        if cancelled and cancelled():
            raise Cancelled()
        try:
            result = fn()
            limiter.speed_up()
            return result
        except AIRateLimitError as exc:
            limiter.slow_down()
            if attempt >= MAX_ATTEMPTS:
                raise
            delay = exc.retry_after if exc.retry_after else min(60.0, 5.0 * 2 ** (attempt - 1))
            _sleep(min(delay, 90.0) + random.uniform(0.0, 1.0), cancelled)
        except AIServerError:
            if attempt >= MAX_ATTEMPTS:
                raise
            _sleep(min(30.0, 2.0 ** attempt) + random.uniform(0.0, 1.0), cancelled)
