import time

import pytest

from ai import ratelimit
from ai.ratelimit import MAX_ATTEMPTS, RateLimiter, call_with_retries
from ai.types import AIConfigError, AIRateLimitError, AIResponseError, AIServerError, Cancelled


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(ratelimit, "_sleep", lambda seconds, cancelled=None: waited.append(seconds) if seconds >= 1 else None)   # ignore the limiter's own tiny waits
    monkeypatch.setattr(ratelimit.random, "uniform", lambda a, b: 0.0)
    return waited


def test_calls_are_spaced_apart():
    limiter = RateLimiter(rpm=600)               # one call every 0.1 s
    start = time.monotonic()
    for _ in range(4):
        limiter.wait()
    assert time.monotonic() - start >= 0.28


def test_limiter_slows_after_a_429_and_recovers():
    limiter = RateLimiter(rpm=60)
    limiter.slow_down()
    limiter.slow_down()
    assert limiter.penalty == pytest.approx(2.25)
    for _ in range(30):
        limiter.speed_up()
    assert limiter.penalty == 1.0
    for _ in range(20):
        limiter.slow_down()
    assert limiter.penalty == 6.0


def test_cancel_stops_the_wait():
    limiter = RateLimiter(rpm=1)
    limiter.wait()
    with pytest.raises(Cancelled):
        limiter.wait(cancelled=lambda: True)


def test_success_needs_one_call(sleeps):
    assert call_with_retries(lambda: "ok", RateLimiter(60000)) == "ok" and sleeps == []


def test_rate_limit_waits_for_the_advised_time_and_slows_down(sleeps):
    limiter = RateLimiter(60000)
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise AIRateLimitError("slow down", retry_after=7)
        return "done"

    assert call_with_retries(fn, limiter) == "done"
    assert len(calls) == 3 and sleeps == [7, 7]


def test_rate_limit_without_advice_backs_off_exponentially(sleeps):
    n = []

    def fn():
        n.append(1)
        if len(n) < 4:
            raise AIRateLimitError("slow down")
        return 1

    call_with_retries(fn, RateLimiter(60000))
    assert sleeps == [5.0, 10.0, 20.0]


def test_gives_up_after_the_last_attempt(sleeps):
    n = []

    def fn():
        n.append(1)
        raise AIRateLimitError("still busy", retry_after=1)

    with pytest.raises(AIRateLimitError):
        call_with_retries(fn, RateLimiter(60000))
    assert len(n) == MAX_ATTEMPTS and len(sleeps) == MAX_ATTEMPTS - 1


def test_server_errors_are_retried_with_backoff(sleeps):
    n = []

    def fn():
        n.append(1)
        if len(n) < 3:
            raise AIServerError("503")
        return "ok"

    assert call_with_retries(fn, RateLimiter(60000)) == "ok" and sleeps == [2.0, 4.0]


@pytest.mark.parametrize("error", [AIConfigError("bad key"), AIResponseError("cut off"), ValueError("bug")])
def test_other_errors_are_not_retried(sleeps, error):
    n = []

    def fn():
        n.append(1)
        raise error

    with pytest.raises(type(error)):
        call_with_retries(fn, RateLimiter(60000))
    assert len(n) == 1 and sleeps == []


def test_cancelled_before_the_call_never_calls(sleeps):
    with pytest.raises(Cancelled):
        call_with_retries(lambda: pytest.fail("must not run"), RateLimiter(60000), cancelled=lambda: True)
