"""Rebuilds the denormalised explorer columns on `websites` from normalised tables."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.adtech.detector import ACTIVE, DECLARED, POSSIBLE
from app.models import (
    AdsTxtFile, Contact, DetectedTechnology, OpportunityAssessment, Outreach, PopularityObservation, Score, Website,
    WebsiteClassification,
)

AD_PARTNER_CATS = ("ssp", "header_bidding", "native", "video", "monetization_partner")


def refresh_summary(db: Session, wid: int) -> None:
    w = db.get(Website, wid)
    if w is None:
        return
    cls = db.scalar(select(WebsiteClassification).where(WebsiteClassification.website_id == wid,
                                                        WebsiteClassification.is_current.is_(True)).order_by(WebsiteClassification.id.desc()).limit(1))
    if cls:
        w.primary_category = cls.primary_category
        w.is_publisher = cls.is_publisher
        w.classification_confidence = cls.confidence

    pops = db.execute(select(PopularityObservation.source, PopularityObservation.country, PopularityObservation.period,
                             PopularityObservation.rank_bucket, PopularityObservation.rank)
                      .where(PopularityObservation.website_id == wid)).all()
    g_periods = [p for s, c, p, b, r in pops if s == "crux" and c == "global"]
    if g_periods:
        lp = max(g_periods)
        w.crux_best_bucket = min(b for s, c, p, b, r in pops if s == "crux" and c == "global" and p == lp and b)
    t_periods = [p for s, c, p, b, r in pops if s == "tranco"]
    if t_periods:
        lp = max(t_periods)
        w.tranco_best_rank = min(r for s, c, p, b, r in pops if s == "tranco" and p == lp and r)
    country = {}
    for s, c, p, b, r in pops:
        if s == "crux" and c != "global" and b:
            country[c] = min(country.get(c, b), b)
    if country:
        w.primary_geo = min(country.items(), key=lambda kv: kv[1])[0]
    elif w.country_signals:
        w.primary_geo = None  # TLD/language signals are not an audience GEO

    dets = db.execute(select(DetectedTechnology.vendor_key, DetectedTechnology.status, DetectedTechnology.category)
                      .where(DetectedTechnology.website_id == wid, DetectedTechnology.is_current.is_(True))).all()
    st = {k: s for k, s, _ in dets}
    if dets:
        w.gam_status = st.get("google_gam")
        w.adsense_status = st.get("google_adsense")
        w.prebid_status = st.get("prebid")
        w.observed_partners = sorted(k for k, s, c in dets if c in AD_PARTNER_CATS and s == ACTIVE and k != "prebid")[:40]
        w.declared_ad_systems_count = sum(1 for k, s, c in dets if s == DECLARED)
        w.monetization_type = _monetization_type(st, {k: c for k, _, c in dets})
    ads = db.scalar(select(AdsTxtFile.status).where(AdsTxtFile.website_id == wid, AdsTxtFile.is_current.is_(True)).order_by(AdsTxtFile.id.desc()).limit(1))
    if ads and not dets:
        w.monetization_type = "UNSCANNED"

    opps = db.scalars(select(OpportunityAssessment.opportunity_type).where(OpportunityAssessment.website_id == wid,
                                                                          OpportunityAssessment.is_current.is_(True))).all()
    w.opportunity_types = sorted(set(opps)) or None
    sc = db.scalar(select(Score).where(Score.website_id == wid, Score.is_current.is_(True)).order_by(Score.id.desc()).limit(1))
    if sc:
        w.score_total, w.queue, w.evidence_confidence = sc.total, sc.queue, sc.evidence_confidence
    n_contacts = db.scalar(select(Contact.id).where(Contact.website_id == wid).limit(1))
    w.contact_status = "FOUND" if n_contacts else "NONE"
    o = db.get(Outreach, wid)
    if o:
        w.outreach_stage = o.stage
    w.summary_updated_at = dt.datetime.now(dt.timezone.utc)


def _monetization_type(st: dict[str, str], cats: dict[str, str]) -> str:
    """Label from runtime (active) evidence first; static-only evidence is marked _UNCONFIRMED."""
    for allowed, suffix in (((ACTIVE,), ""), ((ACTIVE, POSSIBLE), "_UNCONFIRMED")):
        present = lambda k: st.get(k) in allowed  # noqa: E731
        managed = [k for k, c in cats.items() if c == "monetization_partner" and present(k)]
        if managed:
            return "MANAGED_PARTNER" + suffix
        if present("google_gam") and (present("prebid") or present("amazon_aps") or present("pubmatic_openwrap")):
            return "GAM_HEADER_BIDDING" + suffix
        if present("google_gam"):
            return "GAM_ONLY_OBSERVED" + suffix
        if present("google_adsense"):
            return "ADSENSE_ONLY_OBSERVED" + suffix
        if any(st.get(k) in allowed for k, c in cats.items() if c in ("ssp", "native", "video")):
            return "OTHER_AD_TECH" + suffix
    if any(v == "SCAN_INCONCLUSIVE" for v in st.values()):
        return "INCONCLUSIVE"
    return "NONE_OBSERVED"


def refresh_popularity_columns(db: Session, ids: list[int]) -> None:
    """Bulk refresh of popularity summary columns (latest period per source/country)."""
    if not ids:
        return
    db.execute(text("""
        WITH latest AS (
            SELECT website_id, source, country, max(period) AS period
            FROM popularity_observations WHERE website_id = ANY(:ids) GROUP BY 1, 2, 3),
        best AS (
            SELECT p.website_id,
                   min(p.rank_bucket) FILTER (WHERE p.source = 'crux' AND p.country = 'global') AS crux_global,
                   min(p.rank) FILTER (WHERE p.source = 'tranco') AS tranco
            FROM popularity_observations p JOIN latest l USING (website_id, source, country, period)
            GROUP BY 1),
        geo AS (
            SELECT DISTINCT ON (p.website_id) p.website_id, p.country
            FROM popularity_observations p JOIN latest l USING (website_id, source, country, period)
            WHERE p.source = 'crux' AND p.country <> 'global' AND p.rank_bucket IS NOT NULL
            ORDER BY p.website_id, p.rank_bucket, p.country)
        UPDATE websites w SET crux_best_bucket = b.crux_global, tranco_best_rank = b.tranco,
               primary_geo = coalesce(g.country, w.primary_geo), summary_updated_at = now()
        FROM best b LEFT JOIN geo g USING (website_id)
        WHERE w.id = b.website_id
    """), {"ids": list(ids)})
