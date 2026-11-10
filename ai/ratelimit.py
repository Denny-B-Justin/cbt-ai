"""Pace requests to the provider and retry temporary failures. Provider-neutral."""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TypeVar

from .types import AIRateLimitError, AIServerError, Cancelled

T = TypeVar("T")
MAX_ATTEMPTS = 6
WINDOW_S = 60.0


def _sleep(seconds: float, cancelled: Callable[[], bool] | None = None) -> None:
    end = time.monotonic() + seconds
    while True:
        if cancelled and cancelled():
            raise Cancelled()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.25, left))


class RateLimiter:
    """Spaces calls at least 60/rpm seconds apart and keeps the tokens of any 60 seconds within tpm (0: no token limit).

    Slows down after a 429 and recovers on success. Each call reserves its estimated tokens when it starts; settle()
    replaces the estimate with what the model reports it used.
    """

    def __init__(self, rpm: int, tpm: int = 0):
        self.base = 60.0 / max(1, rpm)
        self.tpm = max(0, tpm)
        self.penalty = 1.0
        self._next = 0.0
        self._spent: deque[list[float]] = deque()      # [start time, tokens], oldest first
        self._lock = threading.Lock()

    def _token_start(self, start: float, tokens: float) -> float:
        """The earliest time from start at which tokens more fit in the 60-second window."""
        while self._spent and self._spent[0][0] <= start - 2 * WINDOW_S:
            self._spent.popleft()
        window = [e for e in self._spent if e[0] > start - WINDOW_S]
        excess = sum(k for _, k in window) + tokens - self.tpm
        for t, k in window:
            if excess <= 0:
                break
            excess -= k
            start = t + WINDOW_S
        return start

    def wait(self, cancelled: Callable[[], bool] | None = None, tokens: float = 0) -> list[float]:
        """Blocks until the call may start. Returns its reservation, to pass to settle()."""
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            ticket = [start, 0.0]
            if self.tpm and tokens > 0:
                ticket[1] = min(float(tokens), float(self.tpm))      # a call larger than the budget waits for an empty window
                start = ticket[0] = self._token_start(start, ticket[1])
                self._spent.append(ticket)
            self._next = start + self.base * self.penalty
        if start > now:
            _sleep(start - now, cancelled)
        return ticket

    def settle(self, ticket: list[float], tokens: float | None) -> None:
        """Record what a call really used (0 when it was refused). None keeps the estimate."""
        if tokens is not None:
            with self._lock:
                ticket[1] = min(max(0.0, float(tokens)), float(self.tpm or tokens))

    def slow_down(self) -> None:
        with self._lock:
            self.penalty = min(self.penalty * 1.5, 6.0)

    def speed_up(self) -> None:
        with self._lock:
            self.penalty = max(1.0, self.penalty * 0.9)


def call_with_retries(fn: Callable[[], T], limiter: RateLimiter, cancelled: Callable[[], bool] | None = None,
                      tokens: float = 0, used: Callable[[], int | None] | None = None) -> T:
    """tokens: the estimated size of one attempt. used: returns the tokens the last attempt really used, if known."""
    attempt = 0
    while True:
        attempt += 1
        ticket = limiter.wait(cancelled, tokens)
        if cancelled and cancelled():
            limiter.settle(ticket, 0)
            raise Cancelled()
        try:
            result = fn()
            limiter.speed_up()
            limiter.settle(ticket, used() if used else None)
            return result
        except AIRateLimitError as exc:
            limiter.settle(ticket, 0)                     # a refused call used nothing
            limiter.slow_down()
            if attempt >= MAX_ATTEMPTS:
                raise
            delay = exc.retry_after if exc.retry_after else min(60.0, 5.0 * 2 ** (attempt - 1))
            _sleep(min(delay, 90.0) + random.uniform(0.0, 1.0), cancelled)
        except AIServerError:
            limiter.settle(ticket, used() if used else None)
            if attempt >= MAX_ATTEMPTS:
                raise
            _sleep(min(30.0, 2.0 ** attempt) + random.uniform(0.0, 1.0), cancelled)
        except Exception:
            limiter.settle(ticket, used() if used else None)     # a cut-off answer still used its tokens
            raise
