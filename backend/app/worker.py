"""Celery application: stage workers, job runner, dispatcher and schedules.

Queues (each can get its own worker pool / concurrency):
  jobs     - discovery / import / recompute jobs
  fast     - qualify, score (DB only)
  fetch    - classify, supply (HTTP, async inside each task)
  render   - adtech (Playwright; keep concurrency low)
"""
from __future__ import annotations

import datetime as dt
import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from app.core.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery("purify", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,  # a task lost with its worker is redelivered
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="fast",
    task_routes={
        "app.worker.run_job_task": {"queue": "jobs"},
        "app.worker.stage_task": {"queue": "fast"},
    },
    broker_transport_options={"visibility_timeout": 3 * 3600},
    timezone="UTC",
    beat_schedule={
        "dispatch": {"task": "app.worker.dispatch", "schedule": 20.0},
        "watchdog": {"task": "app.worker.watchdog", "schedule": 300.0},
        "scheduled-discovery": {"task": "app.worker.scheduled_discovery", "schedule": crontab(minute=7)},
    },
)

STAGE_QUEUE = {"qualify": "fast", "score": "fast", "classify": "fetch", "supply": "fetch", "adtech": "render"}


@celery_app.task(name="app.worker.run_job_task")
def run_job_task(job_id: int) -> str:
    from app.jobs.base import run_job

    return run_job(job_id)


@celery_app.task(name="app.worker.stage_task", time_limit=3600, soft_time_limit=3300)
def stage_task(stage: str, ids: list[int]) -> int:
    from app.pipeline.stages import STAGE_RUNNERS

    STAGE_RUNNERS[stage](ids)
    return len(ids)


def _queue_depth(queue: str) -> int:
    try:
        import redis

        return int(redis.Redis.from_url(settings.redis_url).llen(queue))
    except Exception:  # noqa: BLE001
        return 0


@celery_app.task(name="app.worker.dispatch")
def dispatch() -> dict[str, int]:
    """Claim pending work per stage and hand it to the stage queues, without flooding them."""
    from app.pipeline.claims import STAGES, claim
    from app.services.settings_store import get_setting

    cfg = get_setting("dispatcher")
    if cfg.get("paused"):
        return {}
    sent: dict[str, int] = {}
    for stage in STAGES:
        q = STAGE_QUEUE[stage]
        if _queue_depth(q) > 4:  # backpressure: leave work in the DB until workers catch up
            continue
        ids = claim(stage, int(cfg.get(f"{stage}_batch", 50)))
        if ids:
            stage_task.apply_async((stage, ids), queue=q)
            sent[stage] = len(ids)
    return sent


@celery_app.task(name="app.worker.watchdog")
def watchdog() -> list[int]:
    """Re-queue jobs whose worker died (stale heartbeat). Stage leases recover via claim()."""
    from sqlalchemy import update

    from app.core.db import session_scope
    from app.jobs.base import stale_running_jobs
    from app.models import Job

    stale = stale_running_jobs()
    for jid in stale:
        with session_scope() as s:
            s.execute(update(Job).where(Job.id == jid).values(status="QUEUED"))
        run_job_task.delay(jid)
    return stale


def _cron_due(expr: str, now: dt.datetime) -> bool:
    """Minimal 5-field cron check at hour granularity (minute field ignored; runs hourly)."""
    try:
        _m, h, dom, mon, dow = expr.split()
    except ValueError:
        return False

    def ok(field: str, val: int) -> bool:
        return field == "*" or val in {int(x) for x in field.split(",")}

    return ok(h, now.hour) and ok(dom, now.day) and ok(mon, now.month) and ok(dow, (now.isoweekday() % 7))


@celery_app.task(name="app.worker.scheduled_discovery")
def scheduled_discovery() -> list[int]:
    """Autonomous discovery: start configured dataset ingestion jobs when their schedule is due."""
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.jobs.base import create_job
    from app.models import Job
    from app.services.settings_store import get_setting

    now = dt.datetime.now(dt.timezone.utc)
    started: list[int] = []
    sched = get_setting("schedules")
    plan: list[tuple[str, str, dict]] = []
    if sched["crux_global"]["enabled"] and _cron_due(sched["crux_global"]["cron"], now):
        plan.append(("crux_global", "crux_ingest", dict(sched["crux_global"]["params"])))
    if sched["crux_countries"]["enabled"] and _cron_due(sched["crux_countries"]["cron"], now):
        for cc in sched["crux_countries"]["params"].get("countries", []):
            plan.append((f"crux_{cc}", "crux_ingest", {"country": cc, "max_bucket": sched["crux_countries"]["params"].get("max_bucket", 10000)}))
    if sched["tranco"]["enabled"] and _cron_due(sched["tranco"]["cron"], now):
        plan.append(("tranco", "tranco_ingest", dict(sched["tranco"]["params"])))
    if sched["sellers_json"]["enabled"] and _cron_due(sched["sellers_json"]["cron"], now):
        plan.append(("sellers_json", "sellers_discovery", dict(sched["sellers_json"]["params"])))
    for name, kind, params in plan:
        tag = f"{name}:{now:%Y%m%d%H}"
        with session_scope() as s:
            exists = s.scalar(select(Job.id).where(Job.kind == kind, Job.params["schedule_tag"].astext == tag))
        if exists:
            continue
        params["schedule_tag"] = tag
        jid = create_job(kind, params)
        run_job_task.delay(jid)
        started.append(jid)
    return started


@worker_ready.connect
def _on_ready(sender=None, **_):
    log.info("worker ready; queues=%s", [q.name for q in sender.app.amqp.queues.values()] if sender else "?")
