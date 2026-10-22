"""Resumable job framework.

A job row stores params, a checkpoint and progress. Handlers process input in batches and
commit the checkpoint with each batch, so a crashed worker resumes where it stopped. Jobs
whose heartbeat goes stale while RUNNING are re-queued by the watchdog.
"""
from __future__ import annotations

import datetime as dt
import logging
import traceback
from typing import Any, Callable

from sqlalchemy import select, text, update

from app.core.db import session_scope
from app.models import Job

log = logging.getLogger(__name__)
HANDLERS: dict[str, Callable[["JobContext"], None]] = {}
STALE_AFTER = dt.timedelta(minutes=10)


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn

    return deco


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        with session_scope() as s:
            j = s.get(Job, job_id)
            assert j is not None
            self.kind = j.kind
            self.params: dict[str, Any] = dict(j.params or {})
            self.checkpoint: dict[str, Any] = dict(j.checkpoint or {})
            self.progress: dict[str, Any] = dict(j.progress or {})
            self.usage: dict[str, Any] = dict(j.usage or {})
            self.budget: dict[str, Any] = dict(j.budget or {})

    def save(self, *, checkpoint: dict | None = None, **progress: Any) -> None:
        """Persist checkpoint + progress and raise JobCancelled if cancellation was requested."""
        if checkpoint is not None:
            self.checkpoint.update(checkpoint)
        for k, v in progress.items():
            self.progress[k] = v
        now = dt.datetime.now(dt.timezone.utc)
        with session_scope() as s:
            s.execute(update(Job).where(Job.id == self.job_id).values(
                checkpoint=self.checkpoint, progress=self.progress, usage=self.usage, heartbeat_at=now))
            cancel = s.scalar(select(Job.cancel_requested).where(Job.id == self.job_id))
        if cancel:
            raise JobCancelled()

    def incr(self, **counters: int) -> None:
        for k, v in counters.items():
            self.progress[k] = int(self.progress.get(k, 0)) + v


def create_job(kind: str, params: dict[str, Any], user_id: int | None = None, budget: dict | None = None) -> int:
    import app.jobs.handlers  # noqa: F401  (register handlers)

    if kind not in HANDLERS:
        raise ValueError(f"unknown job kind {kind}")
    with session_scope() as s:
        j = Job(kind=kind, params=params, created_by=user_id, budget=budget or {}, checkpoint={}, progress={}, usage={})
        s.add(j)
        s.flush()
        return j.id


def run_job(job_id: int) -> str:
    """Execute (or resume) a job. Idempotent with respect to completed jobs."""
    import app.jobs.handlers  # noqa: F401  (register handlers)
    from app.core.db import get_engine

    # One runner per job: a session-level advisory lock held on a dedicated connection for the whole
    # run. It is released automatically if the worker process dies, so redelivered / watchdog-requeued
    # copies of the same job simply exit instead of running concurrently.
    lock_conn = get_engine().connect()
    got = lock_conn.execute(text("SELECT pg_try_advisory_lock(:k, :j)"), {"k": 7341, "j": job_id}).scalar()
    lock_conn.commit()
    if not got:
        lock_conn.close()
        return "ALREADY_RUNNING"
    try:
        return _run_job_locked(job_id)
    finally:
        try:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k, :j)"), {"k": 7341, "j": job_id})
            lock_conn.commit()
        finally:
            lock_conn.close()


def _run_job_locked(job_id: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    with session_scope() as s:
        j = s.get(Job, job_id)
        if j is None or j.status in ("DONE", "CANCELLED"):
            return j.status if j else "MISSING"
        j.status = "RUNNING"
        j.started_at = j.started_at or now
        j.heartbeat_at = now
        j.error = None
    ctx = JobContext(job_id)
    try:
        HANDLERS[ctx.kind](ctx)
        final, err = "DONE", None
    except JobCancelled:
        final, err = "CANCELLED", None
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        final, err = "FAILED", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-3000:]}"
    with session_scope() as s:
        s.execute(update(Job).where(Job.id == job_id).values(
            status=final, error=err, finished_at=dt.datetime.now(dt.timezone.utc),
            progress=ctx.progress, checkpoint=ctx.checkpoint, usage=ctx.usage))
    return final


def stale_running_jobs() -> list[int]:
    """RUNNING jobs with a stale heartbeat whose runner lock is NOT held (i.e. the runner died)."""
    cutoff = dt.datetime.now(dt.timezone.utc) - STALE_AFTER
    with session_scope() as s:
        ids = list(s.scalars(select(Job.id).where(Job.status.in_(("RUNNING", "QUEUED")), Job.heartbeat_at < cutoff)))
        held = set(s.scalars(text("SELECT objid::int FROM pg_locks WHERE locktype='advisory' AND classid=7341 AND granted")))
    return [i for i in ids if i not in held]
