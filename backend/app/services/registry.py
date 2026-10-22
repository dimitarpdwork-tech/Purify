"""Bulk registration of discovered hosts with provenance (idempotent, batch-friendly)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import PopularityObservation, RegistrableDomain, StageStatus, Website, WebsiteSource
from app.services.normalize import NormalizedHost

FIRST_STAGE = "qualify"


@dataclass
class Discovered:
    norm: NormalizedHost
    source_type: str
    source_ref: str
    original: str | None = None
    payload: dict[str, Any] | None = None
    priority: float = 0.0
    popularity: list[dict[str, Any]] = field(default_factory=list)  # PopularityObservation kwargs


@dataclass
class RegisterStats:
    received: int = 0
    new_websites: int = 0
    existing_websites: int = 0
    duplicates_in_batch: int = 0


def register(session: Session, items: Iterable[Discovered]) -> RegisterStats:
    """Upsert websites and provenance. Safe to re-run with the same input (idempotent)."""
    stats = RegisterStats()
    now = dt.datetime.now(dt.timezone.utc)
    by_host: dict[str, Discovered] = {}
    all_items: list[Discovered] = []
    for it in items:
        stats.received += 1
        all_items.append(it)
        prev = by_host.get(it.norm.host)
        if prev is None or it.priority > prev.priority:
            if prev is not None:
                stats.duplicates_in_batch += 1
            by_host[it.norm.host] = it
        else:
            stats.duplicates_in_batch += 1
    if not by_host:
        return stats

    # registrable domains
    regs = {d.norm.registrable_domain: d.norm.public_suffix for d in by_host.values()}
    session.execute(
        insert(RegistrableDomain)
        .values([{"registrable_domain": r, "public_suffix": s, "created_at": now} for r, s in regs.items()])
        .on_conflict_do_nothing(index_elements=["registrable_domain"])
    )
    dom_ids = dict(
        session.execute(
            select(RegistrableDomain.registrable_domain, RegistrableDomain.id).where(
                RegistrableDomain.registrable_domain.in_(list(regs))
            )
        ).all()
    )

    existing = set(session.scalars(select(Website.host).where(Website.host.in_(list(by_host)))).all())
    rows = [
        {
            "host": h,
            "domain_id": dom_ids[d.norm.registrable_domain],
            "registrable_domain": d.norm.registrable_domain,
            "preferred_origin": d.norm.origin,
            "first_discovered_at": now,
            "last_observed_at": now,
            "discovery_priority": d.priority,
        }
        for h, d in sorted(by_host.items())
        if h not in existing
    ]
    if rows:
        session.execute(insert(Website).values(rows).on_conflict_do_nothing(index_elements=["host"]))
    stats.new_websites = len(rows)
    stats.existing_websites = len(by_host) - len(rows)

    ids = dict(session.execute(select(Website.host, Website.id).where(Website.host.in_(list(by_host)))).all())

    # raise priority / last_observed for existing hosts
    for h in sorted(existing):
        d = by_host[h]
        session.query(Website).filter(Website.id == ids[h]).update(
            {
                Website.last_observed_at: now,
                Website.discovery_priority: _greatest(Website.discovery_priority, d.priority),
            },
            synchronize_session=False,
        )

    # provenance (one row per website/source/ref)
    src_rows: dict[tuple, dict] = {}
    for it in all_items:
        key = (ids[it.norm.host], it.source_type, it.source_ref[:300])
        src_rows[key] = {
            "website_id": key[0], "source_type": it.source_type, "source_ref": key[2],
            "original_value": (it.original or it.norm.original)[:2000], "payload": it.payload,
            "first_seen_at": now, "last_seen_at": now,
        }
    stmt = insert(WebsiteSource).values([src_rows[k] for k in sorted(src_rows)])
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["website_id", "source_type", "source_ref"],
            set_={"last_seen_at": now, "payload": stmt.excluded.payload},
        )
    )

    # popularity observations
    pop_rows: dict[tuple, dict] = {}
    for it in all_items:
        for p in it.popularity:
            row = {"website_id": ids[it.norm.host], "retrieved_at": now, "country": "global", **p}
            key = (row["website_id"], row["source"], row["period"], row["country"])
            prev = pop_rows.get(key)
            # keep the most popular observation when a host appears twice (e.g. www and bare origin)
            if prev is None or _better(row, prev):
                pop_rows[key] = row
    if pop_rows:
        stmt = insert(PopularityObservation).values([pop_rows[k] for k in sorted(pop_rows)])
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["website_id", "source", "period", "country"],
                set_={"rank_bucket": stmt.excluded.rank_bucket, "rank": stmt.excluded.rank, "retrieved_at": now},
            )
        )

        # websites previously skipped for lack of popularity become eligible again
        pop_ids = sorted({r["website_id"] for r in pop_rows.values()})
        session.execute(
            update(StageStatus)
            .where(StageStatus.website_id.in_(pop_ids), StageStatus.stage == FIRST_STAGE, StageStatus.status == "SKIPPED",
                   StageStatus.detail["reason"].astext == "insufficient_popularity")
            .values(status="PENDING", attempts=0, lease_until=None, updated_at=now)
        )

    # first pipeline stage
    session.execute(
        insert(StageStatus)
        .values([{"website_id": ids[h], "stage": FIRST_STAGE, "status": "PENDING", "priority": d.priority,
                  "attempts": 0, "updated_at": now} for h, d in sorted(by_host.items(), key=lambda kv: ids[kv[0]])])
        .on_conflict_do_nothing(index_elements=["website_id", "stage"])
    )
    return stats


def _better(a: dict, b: dict) -> bool:
    ra = a.get("rank") or a.get("rank_bucket") or 10**9
    rb = b.get("rank") or b.get("rank_bucket") or 10**9
    return ra < rb


def _greatest(col, value):
    from sqlalchemy import func

    return func.greatest(col, value)
