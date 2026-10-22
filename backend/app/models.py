"""Database schema.

Design rules (see docs/ARCHITECTURE.md):
* Raw observations (scans, pages, ads.txt files, popularity observations) are stored
  separately from inferred conclusions (classifications, detections, opportunities, scores).
* Conclusions carry an engine version and an `is_current` flag so they can be recomputed
  from stored observations without re-crawling.
* `websites` carries a denormalised summary used by the explorer; it is rebuilt from the
  normalised tables by `app.services.summary.refresh_summary` and is never a source of truth.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="analyst")  # admin | analyst | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


# ---------------------------------------------------------------- domains / websites
class RegistrableDomain(Base):
    __tablename__ = "domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    registrable_domain: Mapped[str] = mapped_column(String(253), unique=True)
    public_suffix: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class Website(Base):
    """One analysable website origin (host). `host` is the identity key with a leading
    `www.` removed; distinct subdomains are distinct websites."""

    __tablename__ = "websites"
    id: Mapped[int] = mapped_column(primary_key=True)
    host: Mapped[str] = mapped_column(String(253), unique=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), index=True)
    registrable_domain: Mapped[str] = mapped_column(String(253), index=True)
    preferred_origin: Mapped[str] = mapped_column(String(300))
    canonical_host: Mapped[str | None] = mapped_column(String(253))  # after redirects
    redirects_to_website_id: Mapped[int | None] = mapped_column(ForeignKey("websites.id"))
    first_discovered_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    last_observed_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    discovery_priority: Mapped[float] = mapped_column(Float, default=0.0, index=True)

    # ---- denormalised summary (rebuilt; never authoritative) ----
    country_signals: Mapped[list[str] | None] = mapped_column(ARRAY(String(8)))
    primary_geo: Mapped[str | None] = mapped_column(String(8), index=True)
    language: Mapped[str | None] = mapped_column(String(16))
    primary_category: Mapped[str | None] = mapped_column(String(40), index=True)
    is_publisher: Mapped[bool | None] = mapped_column(Boolean, index=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    crux_best_bucket: Mapped[int | None] = mapped_column(Integer, index=True)
    tranco_best_rank: Mapped[int | None] = mapped_column(Integer, index=True)
    gam_status: Mapped[str | None] = mapped_column(String(30), index=True)
    adsense_status: Mapped[str | None] = mapped_column(String(30), index=True)
    prebid_status: Mapped[str | None] = mapped_column(String(30), index=True)
    observed_partners: Mapped[list[str] | None] = mapped_column(ARRAY(String(60)))
    declared_ad_systems_count: Mapped[int | None] = mapped_column(Integer)
    monetization_type: Mapped[str | None] = mapped_column(String(40))
    opportunity_types: Mapped[list[str] | None] = mapped_column(ARRAY(String(2)))
    score_total: Mapped[float | None] = mapped_column(Float, index=True)
    queue: Mapped[str | None] = mapped_column(String(40), index=True)
    evidence_confidence: Mapped[float | None] = mapped_column(Float)
    contact_status: Mapped[str] = mapped_column(String(20), default="NONE")
    outreach_stage: Mapped[str] = mapped_column(String(30), default="Discovered", index=True)
    last_analyzed_at: Mapped[dt.datetime | None] = mapped_column(TS, index=True)
    summary_updated_at: Mapped[dt.datetime | None] = mapped_column(TS)

    sources: Mapped[list["WebsiteSource"]] = relationship(back_populates="website")


Index("ix_websites_host_trgm_prefix", Website.host, postgresql_ops={"host": "text_pattern_ops"})
Index("ix_websites_partners", Website.observed_partners, postgresql_using="gin")
Index("ix_websites_opps", Website.opportunity_types, postgresql_using="gin")


class WebsiteSource(Base):
    """Provenance: every way a website was discovered. Many per website."""

    __tablename__ = "website_sources"
    __table_args__ = (UniqueConstraint("website_id", "source_type", "source_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(30), index=True)  # manual|csv|crux|tranco|sellers_json|ads_txt|httparchive|legacy
    source_ref: Mapped[str] = mapped_column(String(300))  # dataset/job identifier
    original_value: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    first_seen_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    last_seen_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    website: Mapped[Website] = relationship(back_populates="sources")


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    domain: Mapped[str | None] = mapped_column(String(253), index=True)
    source: Mapped[str] = mapped_column(String(60))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


# ---------------------------------------------------------------- pipeline state
class StageStatus(Base):
    """Independent status per website per pipeline stage. Leases make crashed work re-claimable."""

    __tablename__ = "stage_status"
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(30), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING|RUNNING|DONE|FAILED|SKIPPED
    priority: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[dt.datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, onupdate=_now)


Index("ix_stage_claim", StageStatus.stage, StageStatus.status, StageStatus.priority.desc())


class Job(Base):
    """Discovery / import / enrichment jobs with checkpoints for resumability."""

    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    budget: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    started_at: Mapped[dt.datetime | None] = mapped_column(TS)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TS)
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(TS)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- popularity
class PopularityObservation(Base):
    """CrUX buckets / Tranco ranks. Popularity only - never presented as visit counts."""

    __tablename__ = "popularity_observations"
    __table_args__ = (UniqueConstraint("website_id", "source", "period", "country"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # crux | tranco
    period: Mapped[str] = mapped_column(String(20))  # e.g. 202609 or list id/date
    country: Mapped[str] = mapped_column(String(8), default="global")
    rank_bucket: Mapped[int | None] = mapped_column(Integer)  # crux: 1000/5000/10000/...
    rank: Mapped[int | None] = mapped_column(Integer)  # tranco exact rank as published
    origin: Mapped[str | None] = mapped_column(String(300))
    retrieved_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    source_url: Mapped[str | None] = mapped_column(Text)



class ProviderUsage(Base):
    __tablename__ = "provider_usage"
    __table_args__ = (UniqueConstraint("provider", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(60))
    day: Mapped[dt.date] = mapped_column()
    requests: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


# ---------------------------------------------------------------- scans (raw observations)
class Scan(Base):
    __tablename__ = "scans"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # http_fetch | rendered | ads_txt
    method: Mapped[str] = mapped_column(String(60))  # httpx | playwright-chromium-<ver>
    status: Mapped[str] = mapped_column(String(20))  # OK | PARTIAL | BLOCKED | FAILED | ROBOTS_DISALLOWED
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TS)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pages: Mapped[list["ScanPage"]] = relationship(back_populates="scan", cascade="all, delete-orphan")


class ScanPage(Base):
    __tablename__ = "scan_pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    page_role: Mapped[str] = mapped_column(String(20))  # homepage | article | category | other
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(120))
    fetched_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    html_sha256: Mapped[str | None] = mapped_column(String(64))
    html_gz: Mapped[bytes | None] = mapped_column(LargeBinary)  # bounded raw evidence
    script_urls: Mapped[list[str] | None] = mapped_column(JSONB)
    network_requests: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    page_globals: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    scan: Mapped[Scan] = relationship(back_populates="pages")


# ---------------------------------------------------------------- inferred conclusions
class WebsiteClassification(Base):
    __tablename__ = "website_classifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    primary_category: Mapped[str] = mapped_column(String(40))
    secondary_categories: Mapped[list[str] | None] = mapped_column(JSONB)
    is_publisher: Mapped[bool | None] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float)
    supporting_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    contradictory_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    features: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pages_inspected: Mapped[list[str]] = mapped_column(JSONB, default=list)
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    method: Mapped[str] = mapped_column(String(20), default="rules")  # rules | llm | manual | legacy_map
    engine_version: Mapped[str] = mapped_column(String(20))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class DetectedTechnology(Base):
    __tablename__ = "detected_technologies"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    vendor_key: Mapped[str] = mapped_column(String(60), index=True)
    vendor_name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))  # DETECTED_ACTIVE_SIGNALS | DECLARED_AUTHORIZATION_ONLY | POSSIBLE | NOT_OBSERVED | SCAN_INCONCLUSIVE
    confidence: Mapped[float] = mapped_column(Float)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    engine_version: Mapped[str] = mapped_column(String(20))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    evidence: Mapped[list["TechnologyEvidence"]] = relationship(cascade="all, delete-orphan")


class TechnologyEvidence(Base):
    __tablename__ = "technology_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    detection_id: Mapped[int] = mapped_column(ForeignKey("detected_technologies.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # script_url | network_request | js_global | html | dom | ads_txt | prebid_config | gpt_slot
    value: Mapped[str] = mapped_column(Text)
    page_url: Mapped[str | None] = mapped_column(Text)
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    observation: Mapped[str] = mapped_column(String(20), default="OBSERVED")  # OBSERVED | DECLARED


class AdInventory(Base):
    __tablename__ = "ad_inventory"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    pages_sampled: Mapped[int] = mapped_column(Integer)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB)  # counts per placement type, slots, sizes
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


# ---------------------------------------------------------------- ads.txt / sellers.json
class AdsTxtFile(Base):
    __tablename__ = "ads_txt_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="ads.txt")  # ads.txt | app-ads.txt
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # FOUND | NOT_FOUND | NOT_TEXT | EMPTY | FETCH_FAILED | ROBOTS_DISALLOWED
    sha256: Mapped[str | None] = mapped_column(String(64))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    malformed_count: Mapped[int] = mapped_column(Integer, default=0)
    variables: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    malformed_sample: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    raw_text: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class AdsTxtRecord(Base):
    __tablename__ = "ads_txt_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("ads_txt_files.id", ondelete="CASCADE"), index=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    ad_system_domain: Mapped[str] = mapped_column(String(253))
    seller_account_id: Mapped[str] = mapped_column(String(200))
    relationship: Mapped[str] = mapped_column(String(10))  # DIRECT | RESELLER
    cert_authority_id: Mapped[str | None] = mapped_column(String(100))
    vendor_key: Mapped[str | None] = mapped_column(String(60), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


Index("ix_adstxt_system_account", AdsTxtRecord.ad_system_domain, AdsTxtRecord.seller_account_id)


class SellersJsonFile(Base):
    __tablename__ = "sellers_json_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    ad_system_domain: Mapped[str] = mapped_column(String(253), index=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    seller_count: Mapped[int] = mapped_column(Integer, default=0)
    publisher_domain_count: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class SellerEntity(Base):
    __tablename__ = "seller_entities"
    __table_args__ = (UniqueConstraint("ad_system_domain", "seller_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ad_system_domain: Mapped[str] = mapped_column(String(253))
    seller_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(253), index=True)
    seller_type: Mapped[str | None] = mapped_column(String(20))  # PUBLISHER | INTERMEDIARY | BOTH
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("sellers_json_files.id", ondelete="SET NULL"))
    fetched_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


# ---------------------------------------------------------------- opportunity & scores
class OpportunityAssessment(Base):
    __tablename__ = "opportunity_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    opportunity_type: Mapped[str] = mapped_column(String(2))  # A..G
    label: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    hypothesis: Mapped[str] = mapped_column(Text)
    missing_information: Mapped[list[str]] = mapped_column(JSONB, default=list)
    verification_step: Mapped[str] = mapped_column(Text)
    suggested_approach: Mapped[str] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(String(20))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class Score(Base):
    __tablename__ = "scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    popularity: Mapped[float] = mapped_column(Float)
    ad_opportunity: Mapped[float] = mapped_column(Float)
    audience_geo: Mapped[float] = mapped_column(Float)
    inventory: Mapped[float] = mapped_column(Float)
    actionability: Mapped[float] = mapped_column(Float)
    evidence_quality: Mapped[float] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)
    computed_queue: Mapped[str] = mapped_column(String(40))
    queue: Mapped[str] = mapped_column(String(40))  # after manual override
    evidence_confidence: Mapped[float] = mapped_column(Float)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    missing_critical: Mapped[list[str]] = mapped_column(JSONB, default=list)
    next_action: Mapped[str] = mapped_column(Text)
    weights: Mapped[dict[str, Any]] = mapped_column(JSONB)
    engine_version: Mapped[str] = mapped_column(String(20))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class ManualOverride(Base):
    __tablename__ = "manual_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(40))  # queue | primary_category | excluded
    value: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


# ---------------------------------------------------------------- commercial workflow
class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(30), default="PUBLISHED_ON_SOURCE")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    last_checked_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class Outreach(Base):
    __tablename__ = "outreach_status"
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(30), default="Discovered")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    imported_status: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, onupdate=_now)


class ExclusionRule(Base):
    __tablename__ = "exclusion_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # host | registrable | suffix | keyword
    pattern: Mapped[str] = mapped_column(String(253))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class HistoricalChange(Base):
    __tablename__ = "historical_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    before: Mapped[Any] = mapped_column(JSONB)
    after: Mapped[Any] = mapped_column(JSONB)
    detected_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, onupdate=_now)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class SavedView(Base):
    __tablename__ = "saved_views"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    columns: Mapped[list[str] | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    at: Mapped[dt.datetime] = mapped_column(TS, default=_now, server_default=func.now())
