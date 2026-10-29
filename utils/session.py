"""Memory-only visitor sessions and the background jobs they run.

Nothing here touches the disk. A session disappears when the visitor closes the page, or after a quiet period.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from ai.types import AIError, Cancelled
from tagging.pipeline import AnalysisError

from . import constants as C

log = logging.getLogger(__name__)

RUNNING, DONE, FAILED, CANCELLED = "running", "done", "failed", "cancelled"
SWEEP_SECONDS = 30
GENERIC_ERROR = "Something went wrong while analysing the document. Please try again."
BUSY_ERROR = "The tool is busy with other documents right now. Please try again in a minute."

Work = Callable[[Callable[..., None], Callable[[], bool]], Any]


class Busy(Exception):
    """Too many analyses are running at the same time."""


@dataclass
class Job:
    id: str
    slot: str
    started: float = field(default_factory=time.time)
    state: str = RUNNING
    stage: str = C.STAGE_UPLOAD
    detail: str = ""
    finished: float = 0.0
    result: Any = None
    error: str = ""
    stop: threading.Event = field(default_factory=threading.Event)

    def set_stage(self, stage: str, detail: str = "") -> None:
        if not self.stop.is_set():
            self.stage, self.detail = stage, detail

    def cancelled(self) -> bool:
        return self.stop.is_set()

    @property
    def seconds(self) -> float:
        return (self.finished or time.time()) - self.started


@dataclass
class Upload:
    name: str
    data: bytes


@dataclass
class Session:
    id: str
    last_seen: float = field(default_factory=time.time)
    jobs: Dict[str, Job] = field(default_factory=dict)
    uploads: Dict[str, Upload] = field(default_factory=dict)


_sessions: Dict[str, Session] = {}
_lock = threading.RLock()
_sweeper: Optional[threading.Thread] = None


def new_id() -> str:
    return uuid.uuid4().hex


def idle_seconds() -> int:
    return C.env_int(C.ENV_SESSION_MINUTES, C.DEFAULT_SESSION_MINUTES) * 60


def _ensure_sweeper() -> None:
    global _sweeper
    if _sweeper and _sweeper.is_alive():
        return

    def loop() -> None:
        while True:
            time.sleep(SWEEP_SECONDS)
            try:
                sweep()
            except Exception:                                    # never let the cleaner die
                log.exception("Session cleanup failed")

    _sweeper = threading.Thread(target=loop, name="session-sweeper", daemon=True)
    _sweeper.start()


def _stop_jobs(session: Session) -> None:
    for job in session.jobs.values():
        job.stop.set()


# ── sessions ────────────────────────────────────────────────────────────────
def get(sid: Optional[str]) -> Optional[Session]:
    with _lock:
        return _sessions.get(sid) if sid else None


def ensure(sid: str) -> Session:
    with _lock:
        session = _sessions.get(sid)
        if session is None:
            session = _sessions[sid] = Session(sid)
            _ensure_sweeper()
        session.last_seen = time.time()
        return session


def touch(sid: Optional[str]) -> bool:
    with _lock:
        session = _sessions.get(sid) if sid else None
        if session:
            session.last_seen = time.time()
        return session is not None


def end(sid: Optional[str]) -> bool:
    """Remove a visitor's session and everything in it."""
    with _lock:
        session = _sessions.pop(sid, None) if sid else None
    if session:
        _stop_jobs(session)
        session.uploads.clear()
    return session is not None


def sweep(now: Optional[float] = None, limit: Optional[float] = None) -> int:
    now = time.time() if now is None else now
    limit = idle_seconds() if limit is None else limit
    with _lock:
        stale = [sid for sid, s in _sessions.items() if now - s.last_seen > limit]
    return sum(end(sid) for sid in stale)


def count() -> int:
    with _lock:
        return len(_sessions)


def clear_all() -> None:
    with _lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for s in sessions:
        _stop_jobs(s)


# ── uploads kept between a file being dropped and the run ───────────────────
def set_upload(sid: str, key: str, name: str, data: bytes) -> None:
    ensure(sid).uploads[key] = Upload(name, data)


def get_upload(sid: Optional[str], key: str) -> Optional[Upload]:
    session = get(sid)
    return session.uploads.get(key) if session else None


def drop_upload(sid: Optional[str], key: str) -> None:
    session = get(sid)
    if session:
        session.uploads.pop(key, None)


# ── jobs ────────────────────────────────────────────────────────────────────
def running_jobs() -> int:
    with _lock:
        return sum(1 for s in _sessions.values() for j in s.jobs.values() if j.state == RUNNING)


def current_job(sid: Optional[str], slot: str) -> Optional[Job]:
    session = get(sid)
    return session.jobs.get(slot) if session else None


def _run(job: Job, work: Work) -> None:
    try:
        job.result = work(job.set_stage, job.cancelled)
        job.state = CANCELLED if job.stop.is_set() else DONE
    except Cancelled:
        job.state = CANCELLED
    except AnalysisError as exc:
        job.state, job.error = FAILED, str(exc)
    except AIError as exc:
        job.state, job.error = FAILED, exc.user_message
    except Exception:
        log.exception("Analysis failed")
        job.state, job.error = FAILED, GENERIC_ERROR
    finally:
        if job.stop.is_set():                                    # the visitor stopped it: whatever happened later does not matter
            job.state, job.error = CANCELLED, ""
        job.finished = time.time()
        if job.state != DONE:
            job.result = None


def start_job(sid: str, slot: str, work: Work) -> Job:
    """Start `work(progress, cancelled)` in the background. A job already running in this slot is stopped first."""
    with _lock:
        if running_jobs() >= C.env_int(C.ENV_MAX_JOBS, C.DEFAULT_MAX_JOBS):
            raise Busy()
        session = ensure(sid)
        previous = session.jobs.get(slot)
        if previous:
            previous.stop.set()
        job = session.jobs[slot] = Job(new_id(), slot)
    threading.Thread(target=_run, args=(job, work), name="job-" + slot, daemon=True).start()
    return job


def cancel_job(sid: Optional[str], slot: str) -> None:
    job = current_job(sid, slot)
    if job and job.state == RUNNING:
        job.stop.set()
        job.state, job.finished = CANCELLED, time.time()


def forget_job(sid: Optional[str], slot: str) -> None:
    session = get(sid)
    if session:
        job = session.jobs.pop(slot, None)
        if job:
            job.stop.set()
