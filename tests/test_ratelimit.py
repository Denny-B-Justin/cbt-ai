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


# ── tokens per minute ───────────────────────────────────────────────────────
@pytest.fixture
def short_window(monkeypatch):
    monkeypatch.setattr(ratelimit, "WINDOW_S", 0.4)


def test_calls_within_the_token_budget_do_not_wait(short_window):
    limiter = RateLimiter(rpm=60000, tpm=1000)
    start = time.monotonic()
    for _ in range(4):
        limiter.wait(tokens=250)
    assert time.monotonic() - start < 0.1


def test_a_call_over_the_token_budget_waits_for_the_window_to_free(short_window):
    limiter = RateLimiter(rpm=60000, tpm=1000)
    start = time.monotonic()
    limiter.wait(tokens=700)
    limiter.wait(tokens=700)
    assert time.monotonic() - start >= 0.38


def test_a_call_larger_than_the_budget_still_runs_alone(short_window):
    limiter = RateLimiter(rpm=60000, tpm=1000)
    assert limiter.wait(tokens=5000)[1] == 1000
    start = time.monotonic()
    limiter.wait(tokens=10)
    assert time.monotonic() - start >= 0.38


def test_the_real_count_replaces_the_estimate(short_window):
    limiter = RateLimiter(rpm=60000, tpm=1000)
    limiter.settle(limiter.wait(tokens=900), 100)
    start = time.monotonic()
    limiter.wait(tokens=800)
    assert time.monotonic() - start < 0.1


def test_a_refused_call_gives_its_tokens_back(sleeps):
    limiter = RateLimiter(rpm=60000, tpm=1000)
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise AIRateLimitError("slow down", retry_after=2)
        return "ok"

    assert call_with_retries(fn, limiter, tokens=600, used=lambda: 450) == "ok"
    assert [k for _, k in limiter._spent] == [0, 450]


def test_a_cut_off_answer_still_counts_its_tokens(sleeps):
    limiter = RateLimiter(rpm=60000, tpm=1000)

    def fn():
        raise AIResponseError("cut off", truncated=True)

    with pytest.raises(AIResponseError):
        call_with_retries(fn, limiter, tokens=300, used=lambda: 900)
    assert [k for _, k in limiter._spent] == [900]


def test_no_token_budget_means_no_token_bookkeeping():
    limiter = RateLimiter(rpm=60000)
    limiter.wait(tokens=10 ** 9)
    assert not limiter._spent


@pytest.mark.parametrize("usage, total", [
    ({"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}, 150),      # GPT
    ({"inputTokens": 70, "outputTokens": 30, "totalTokens": 100}, 100),          # Claude
    ({"total_input_tokens": 40, "total_output_tokens": 20}, 60),                 # Gemini
    ({}, None), (None, None)])
def test_each_model_familys_usage_is_read(usage, total):
    from ai import provider_common
    provider_common.reset_usage()
    provider_common.record_usage(usage)
    assert provider_common.last_usage() == total


def test_the_estimate_grows_with_what_is_sent():
    from ai.client import estimate_tokens
    from ai.types import Attachment
    small = estimate_tokens("sys", "x" * 300, {}, (), 1024)
    big = estimate_tokens("sys", "x" * 30000, {}, [Attachment("application/pdf", b"0" * 60000)], 32768)
    assert small < 1500 and big > 10000 + 1000 + 8192
