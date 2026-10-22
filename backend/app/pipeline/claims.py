"""Stage claiming with leases (crash-safe) and stage transitions."""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import session_scope
from app.models import StageStatus

STAGES = ("qualify", "classify", "supply", "adtech", "score")
NEXT = {"qualify": "classify", "classify": "supply", "supply": "adtech", "adtech": "score", "score": None}


def claim(stage: str, limit: int) -> list[int]:
    """Atomically claim up to `limit` PENDING (or lease-expired RUNNING) rows for a stage."""
    s = get_settings()
    with session_scope() as db:
        rows = db.execute(text("""
            UPDATE stage_status SET status='RUNNING', attempts=attempts+1, updated_at=now(),
                   lease_until = now() + make_interval(secs => :lease)
            WHERE (website_id, stage) IN (
                SELECT website_id, stage FROM stage_status
                WHERE stage = :stage
                  AND ((status = 'PENDING' AND (lease_until IS NULL OR lease_until < now()))
                       OR (status = 'RUNNING' AND lease_until < now()))
                  AND attempts < :max_attempts
                ORDER BY priority DESC, website_id
                LIMIT :limit
                FOR UPDATE SKIP LOCKED)
            RETURNING website_id
        """), {"stage": stage, "limit": limit, "lease": s.stage_lease_seconds, "max_attempts": s.stage_max_attempts}).all()
        # rows whose lease expired too many times become FAILED instead of looping forever
        db.execute(text("""
            UPDATE stage_status SET status='FAILED', last_error=coalesce(last_error,'') || ' | lease expired after max attempts', updated_at=now()
            WHERE stage=:stage AND status IN ('RUNNING','PENDING') AND attempts >= :max_attempts AND lease_until < now()
        """), {"stage": stage, "max_attempts": s.stage_max_attempts})
    return [r[0] for r in rows]


def complete(db: Session, website_id: int, stage: str, status: str = "DONE", detail: dict[str, Any] | None = None,
             advance: bool = True, next_priority: float | None = None) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    db.execute(
        StageStatus.__table__.update()
        .where(StageStatus.website_id == website_id, StageStatus.stage == stage)
        .values(status=status, detail=detail, lease_until=None, last_error=None, updated_at=now)
    )
    nxt = NEXT.get(stage)
    if advance and nxt and status == "DONE":
        enqueue(db, website_id, nxt, next_priority)


def enqueue(db: Session, website_id: int, stage: str, priority: float | None = None) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    if priority is None:
        priority = db.execute(text("SELECT discovery_priority FROM websites WHERE id=:i"), {"i": website_id}).scalar() or 0
    stmt = insert(StageStatus).values(website_id=website_id, stage=stage, status="PENDING", priority=priority, attempts=0, updated_at=now)
    db.execute(stmt.on_conflict_do_update(
        index_elements=["website_id", "stage"],
        set_={"status": "PENDING", "attempts": 0, "lease_until": None, "priority": priority, "updated_at": now},
        where=(StageStatus.status != "RUNNING"),
    ))


def fail(website_id: int, stage: str, error: str) -> None:
    """Record a failure; retry with exponential backoff until max attempts, then FAILED."""
    s = get_settings()
    with session_scope() as db:
        row = db.get(StageStatus, (website_id, stage))
        if row is None:
            return
        row.last_error = error[:2000]
        row.updated_at = dt.datetime.now(dt.timezone.utc)
        if row.attempts >= s.stage_max_attempts:
            row.status = "FAILED"
            row.lease_until = None
        else:
            row.status = "PENDING"
            row.lease_until = row.updated_at + dt.timedelta(seconds=60 * (4 ** max(0, row.attempts - 1)))
