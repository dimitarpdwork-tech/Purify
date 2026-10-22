"""Server-side filtering/sorting for the publisher explorer, discovery queries and exports."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, select
from sqlalchemy.sql import Select

from app.models import AdsTxtRecord, DetectedTechnology, Website, WebsiteSource

SORTABLE = {
    "host": Website.host, "score_total": Website.score_total, "crux_best_bucket": Website.crux_best_bucket,
    "tranco_best_rank": Website.tranco_best_rank, "last_analyzed_at": Website.last_analyzed_at,
    "primary_category": Website.primary_category, "classification_confidence": Website.classification_confidence,
    "evidence_confidence": Website.evidence_confidence, "first_discovered_at": Website.first_discovered_at,
    "queue": Website.queue, "discovery_priority": Website.discovery_priority,
}
PRESENT_STATUSES = ("DETECTED_ACTIVE_SIGNALS", "POSSIBLE")


class VendorCondition(BaseModel):
    vendor: str
    statuses: list[str] = Field(default_factory=lambda: list(PRESENT_STATUSES))


class WebsiteFilter(BaseModel):
    q: str | None = None  # host prefix / substring
    ids: list[int] | None = None
    categories: list[str] | None = None
    is_publisher: bool | None = None
    queues: list[str] | None = None
    opportunity_types: list[str] | None = None
    max_crux_bucket: int | None = None
    max_tranco_rank: int | None = None
    geos: list[str] | None = None
    monetization_types: list[str] | None = None
    gam: list[str] | None = None  # statuses
    adsense: list[str] | None = None
    prebid: list[str] | None = None
    has_vendors: list[VendorCondition] | None = None  # all must match
    lacks_vendors: list[str] | None = None  # none of these present (active/possible)
    ads_txt_systems: list[str] | None = None  # declares any of these ad systems
    seller_account_id: str | None = None
    min_score: float | None = None
    excluded: bool | None = False
    sources: list[str] | None = None
    outreach_stages: list[str] | None = None
    analyzed: bool | None = None
    sort: list[str] = Field(default_factory=lambda: ["-score_total", "crux_best_bucket"])


def apply(stmt: Select, f: WebsiteFilter) -> Select:
    c = []
    if f.q:
        q = f.q.strip().lower()
        c.append(Website.host.like(f"{q}%") if "." in q else Website.host.contains(q))
    if f.ids:
        c.append(Website.id.in_(f.ids))
    if f.categories:
        c.append(Website.primary_category.in_(f.categories))
    if f.is_publisher is not None:
        c.append(Website.is_publisher.is_(f.is_publisher))
    if f.queues:
        c.append(Website.queue.in_(f.queues))
    if f.opportunity_types:
        c.append(Website.opportunity_types.overlap(f.opportunity_types))
    if f.max_crux_bucket:
        c.append(Website.crux_best_bucket <= f.max_crux_bucket)
    if f.max_tranco_rank:
        c.append(Website.tranco_best_rank <= f.max_tranco_rank)
    if f.geos:
        c.append(Website.primary_geo.in_([g.upper() for g in f.geos]))
    if f.monetization_types:
        c.append(Website.monetization_type.in_(f.monetization_types))
    for col, val in ((Website.gam_status, f.gam), (Website.adsense_status, f.adsense), (Website.prebid_status, f.prebid)):
        if val:
            c.append(col.in_(val))
    for vc in f.has_vendors or []:
        c.append(exists().where(DetectedTechnology.website_id == Website.id, DetectedTechnology.is_current.is_(True),
                                DetectedTechnology.vendor_key == vc.vendor, DetectedTechnology.status.in_(vc.statuses)))
    if f.lacks_vendors:
        c.append(~exists().where(DetectedTechnology.website_id == Website.id, DetectedTechnology.is_current.is_(True),
                                 DetectedTechnology.vendor_key.in_(f.lacks_vendors), DetectedTechnology.status.in_(PRESENT_STATUSES)))
    if f.ads_txt_systems:
        c.append(exists().where(AdsTxtRecord.website_id == Website.id, AdsTxtRecord.is_current.is_(True),
                                AdsTxtRecord.ad_system_domain.in_([s.lower() for s in f.ads_txt_systems])))
    if f.seller_account_id:
        c.append(exists().where(AdsTxtRecord.website_id == Website.id, AdsTxtRecord.is_current.is_(True),
                                AdsTxtRecord.seller_account_id == f.seller_account_id))
    if f.min_score is not None:
        c.append(Website.score_total >= f.min_score)
    if f.excluded is not None:
        c.append(Website.excluded.is_(f.excluded))
    if f.sources:
        c.append(exists().where(WebsiteSource.website_id == Website.id, WebsiteSource.source_type.in_(f.sources)))
    if f.outreach_stages:
        c.append(Website.outreach_stage.in_(f.outreach_stages))
    if f.analyzed is True:
        c.append(Website.last_analyzed_at.is_not(None))
    elif f.analyzed is False:
        c.append(Website.last_analyzed_at.is_(None))
    if c:
        stmt = stmt.where(and_(*c))
    order = []
    for key in f.sort or []:
        desc = key.startswith("-")
        col = SORTABLE.get(key.lstrip("-"))
        if col is not None:
            order.append(col.desc().nulls_last() if desc else col.asc().nulls_last())
    order.append(Website.id.asc())
    return stmt.order_by(*order)


def count(db, f: WebsiteFilter) -> int:
    sub = apply(select(Website.id), WebsiteFilter(**{**f.model_dump(), "sort": []})).order_by(None).subquery()
    return db.scalar(select(func.count()).select_from(sub))

