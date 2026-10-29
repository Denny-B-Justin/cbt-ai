"""utils/session.py: visitor sessions, uploads kept in memory, and background jobs."""

import threading
import time

import pytest

from ai.types import AIQuotaError, Cancelled
from tagging.pipeline import AnalysisError
from utils import constants as C
from utils import session


def wait_for(condition, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def join_workers(seconds=3.0):
    for t in threading.enumerate():
        if t.name.startswith("job-"):
            t.join(seconds)


def finished(job):
    return wait_for(lambda: job.state != session.RUNNING and job.finished > 0)


# ── sessions ────────────────────────────────────────────────────────────────
def test_ids_are_unique_and_unguessable():
    ids = {session.new_id() for _ in range(200)}
    assert len(ids) == 200 and all(len(i) == 32 for i in ids)


def test_a_session_starts_empty_and_is_remembered():
    sid = session.new_id()
    assert session.get(sid) is None and session.count() == 0
    s = session.ensure(sid)
    assert session.get(sid) is s and session.count() == 1 and session.ensure(sid) is s


def test_unknown_and_empty_ids_are_harmless():
    assert session.get(None) is None and session.get("") is None
    assert session.touch("nope") is False and session.touch(None) is False
    assert session.end("nope") is False and session.end(None) is False
    assert session.get_upload("nope", "k") is None and session.current_job("nope", "x") is None
    session.drop_upload("nope", "k")
    session.cancel_job("nope", "x")
    session.forget_job("nope", "x")


def test_touching_keeps_a_session_alive():
    sid = session.new_id()
    s = session.ensure(sid)
    s.last_seen -= 1000
    assert session.touch(sid) is True and time.time() - s.last_seen < 5


def test_ending_a_session_removes_everything_in_it():
    sid = session.new_id()
    session.set_upload(sid, "a", "a.pdf", b"secret")
    s = session.get(sid)
    assert session.end(sid) is True
    assert session.get(sid) is None and session.get_upload(sid, "a") is None and s.uploads == {}
    assert session.end(sid) is False


def test_quiet_sessions_are_swept_and_active_ones_kept():
    old, fresh = session.new_id(), session.new_id()
    session.ensure(old).last_seen = 1000.0
    session.ensure(fresh).last_seen = 1500.0
    assert session.sweep(now=2000.0, limit=600) == 1
    assert session.get(old) is None and session.get(fresh) is not None


def test_the_quiet_period_comes_from_the_settings(monkeypatch):
    monkeypatch.setenv(C.ENV_SESSION_MINUTES, "2")
    assert session.idle_seconds() == 120
    monkeypatch.delenv(C.ENV_SESSION_MINUTES)
    assert session.idle_seconds() == C.DEFAULT_SESSION_MINUTES * 60


def test_sweeping_stops_the_jobs_of_removed_sessions():
    sid = session.new_id()
    gate = threading.Event()
    job = session.start_job(sid, "evaluate", lambda progress, cancelled: gate.wait(5))
    session.get(sid).last_seen = 0.0
    session.sweep(now=10 ** 9, limit=60)
    assert job.stop.is_set()
    gate.set()


def test_clear_all_forgets_everyone():
    for _ in range(3):
        session.ensure(session.new_id())
    session.clear_all()
    assert session.count() == 0


# ── uploads ─────────────────────────────────────────────────────────────────
def test_an_upload_is_kept_until_dropped():
    sid = session.new_id()
    session.set_upload(sid, "a", "budget.pdf", b"123")
    got = session.get_upload(sid, "a")
    assert (got.name, got.data) == ("budget.pdf", b"123")
    session.set_upload(sid, "a", "other.pdf", b"4")
    assert session.get_upload(sid, "a").name == "other.pdf"
    session.drop_upload(sid, "a")
    assert session.get_upload(sid, "a") is None


def test_uploads_of_two_visitors_never_mix():
    a, b = session.new_id(), session.new_id()
    session.set_upload(a, "a", "mine.pdf", b"1")
    assert session.get_upload(b, "a") is None
    session.end(a)
    assert session.get_upload(a, "a") is None


# ── jobs ────────────────────────────────────────────────────────────────────
def test_a_job_reports_its_progress_and_result():
    sid = session.new_id()

    def work(progress, cancelled):
        progress(C.STAGE_TAG, "3 of 9 lines")
        return {"answer": 42}

    job = session.start_job(sid, "evaluate", work)
    assert finished(job)
    assert job.state == session.DONE and job.result == {"answer": 42} and job.error == ""
    assert (job.stage, job.detail) == (C.STAGE_TAG, "3 of 9 lines")
    assert session.current_job(sid, "evaluate") is job and job.seconds >= 0


@pytest.mark.parametrize("error,message", [
    (AnalysisError("Please upload a PDF."), "Please upload a PDF."),
    (AIQuotaError("RESOURCE_EXHAUSTED"), AIQuotaError.user_message),
    (ValueError("secret detail"), session.GENERIC_ERROR)])
def test_failures_become_safe_messages(error, message):
    def work(progress, cancelled):
        raise error

    job = session.start_job(session.new_id(), "evaluate", work)
    assert finished(job)
    assert job.state == session.FAILED and job.error == message and job.result is None
    assert "RESOURCE_EXHAUSTED" not in job.error and "secret" not in job.error


def test_a_cancelled_worker_is_marked_cancelled_not_failed():
    def work(progress, cancelled):
        raise Cancelled()

    job = session.start_job(session.new_id(), "evaluate", work)
    assert finished(job) and job.state == session.CANCELLED and job.error == ""


def test_cancelling_stops_a_running_job_at_once():
    sid = session.new_id()
    started, release = threading.Event(), threading.Event()

    def work(progress, cancelled):
        started.set()
        release.wait(5)
        return "late result"

    job = session.start_job(sid, "evaluate", work)
    assert started.wait(3)
    session.cancel_job(sid, "evaluate")
    assert job.state == session.CANCELLED and job.stop.is_set() and job.cancelled()
    release.set()
    join_workers()
    assert job.state == session.CANCELLED and job.result is None, "a result that arrives late must not bring the job back"


def test_an_error_after_cancelling_does_not_show_as_a_failure():
    sid = session.new_id()
    started, release = threading.Event(), threading.Event()

    def work(progress, cancelled):
        started.set()
        release.wait(5)
        raise AnalysisError("The connection dropped")

    job = session.start_job(sid, "evaluate", work)
    assert started.wait(3)
    session.cancel_job(sid, "evaluate")
    release.set()
    join_workers()
    assert job.state == session.CANCELLED and job.error == ""


def test_progress_after_cancelling_is_ignored():
    job = session.Job("j", "evaluate")
    job.set_stage(C.STAGE_FIND, "1")
    job.stop.set()
    job.set_stage(C.STAGE_TAG, "2")
    assert (job.stage, job.detail) == (C.STAGE_FIND, "1")


def test_starting_again_in_a_slot_stops_the_old_job():
    sid = session.new_id()
    release = threading.Event()
    first = session.start_job(sid, "evaluate", lambda progress, cancelled: release.wait(5))
    second = session.start_job(sid, "evaluate", lambda progress, cancelled: "new")
    assert first.stop.is_set() and session.current_job(sid, "evaluate") is second and finished(second) and second.result == "new"
    release.set()


def test_two_slots_run_side_by_side():
    sid = session.new_id()
    release = threading.Event()
    a = session.start_job(sid, "evaluate", lambda progress, cancelled: release.wait(5))
    b = session.start_job(sid, "compare", lambda progress, cancelled: "done")
    assert finished(b) and a.state == session.RUNNING and not a.stop.is_set()
    release.set()


def test_too_many_analyses_at_once_are_refused(monkeypatch):
    monkeypatch.setenv(C.ENV_MAX_JOBS, "2")
    release = threading.Event()
    jobs = [session.start_job(session.new_id(), "evaluate", lambda p, c: release.wait(5)) for _ in range(2)]
    assert session.running_jobs() == 2
    with pytest.raises(session.Busy):
        session.start_job(session.new_id(), "evaluate", lambda p, c: None)
    release.set()
    assert all(finished(j) for j in jobs)
    assert wait_for(lambda: session.running_jobs() == 0)
    assert finished(session.start_job(session.new_id(), "evaluate", lambda p, c: None))


def test_ending_a_session_stops_its_jobs():
    sid = session.new_id()
    release = threading.Event()
    job = session.start_job(sid, "evaluate", lambda progress, cancelled: release.wait(5))
    session.end(sid)
    assert job.stop.is_set() and session.current_job(sid, "evaluate") is None
    release.set()


def test_forgetting_a_job_clears_the_slot():
    sid = session.new_id()
    job = session.start_job(sid, "evaluate", lambda p, c: "x")
    assert finished(job)
    session.forget_job(sid, "evaluate")
    assert session.current_job(sid, "evaluate") is None


def test_the_worker_can_check_for_cancellation():
    sid = session.new_id()
    flags = []
    started = threading.Event()

    def work(progress, cancelled):
        started.set()
        end = time.time() + 3
        while not cancelled() and time.time() < end:
            time.sleep(0.01)
        flags.append(cancelled())
        raise Cancelled()

    job = session.start_job(sid, "evaluate", work)
    assert started.wait(3)
    session.cancel_job(sid, "evaluate")
    assert finished(job) and wait_for(lambda: flags == [True])
