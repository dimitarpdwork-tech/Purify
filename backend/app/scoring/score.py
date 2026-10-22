"""Transparent priority scoring (0-100) and ranking queues.

Traffic estimates are intentionally not part of this build (traffic is researched manually).
The first component is therefore *popularity* from CrUX buckets / Tranco ranks. It ranks
websites for research; it is never presented as visits.

Missing data scores zero and is listed under `missing_critical`.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from app.adtech.detector import ACTIVE, INCONCLUSIVE
from app.scoring.opportunity import EvidenceBundle, Opportunity

ENGINE_VERSION = "score-1.0"

DEFAULT_WEIGHTS: dict[str, Any] = {
    "max": {"popularity": 30, "ad_opportunity": 25, "audience_geo": 15, "inventory": 15, "actionability": 10, "evidence_quality": 5},
    "crux_bucket_points": {"1000": 30, "5000": 27, "10000": 25, "50000": 20, "100000": 16, "500000": 9, "1000000": 5},
    "tranco_rank_points": [[1000, 26], [10000, 22], [50000, 17], [100000, 14], [500000, 8], [1000000, 4]],
    "opportunity_base": {"A": 20, "B": 22, "C": 18, "D": 10, "E": 14, "F": 6, "G": 4},
    "geo_tiers": {
        "1": ["US", "GB", "CA", "AU", "NZ", "DE", "FR", "NL", "BE", "CH", "AT", "SE", "NO", "DK", "FI", "IE", "JP", "SG", "LU"],
        "2": ["ES", "IT", "PT", "PL", "CZ", "SK", "KR", "AE", "SA", "IL", "HK", "TW", "SI", "EE", "LT", "LV", "HU", "GR", "HR"],
    },
    "geo_tier_multiplier": {"1": 1.0, "2": 0.7, "other": 0.4},
    "category_inventory_points": {
        "NEWS_PUBLISHER": 8, "ENTERTAINMENT_PUBLISHER": 8, "SPORTS_PUBLISHER": 8, "GAMING_PUBLISHER": 8, "LIFESTYLE_PUBLISHER": 8,
        "TECHNOLOGY_PUBLISHER": 7, "FINANCE_PUBLISHER": 7, "EDUCATIONAL_PUBLISHER": 6, "FORUM_COMMUNITY": 6, "CONTENT_TOOL": 5,
        "GENERAL_CONTENT_PUBLISHER": 6,
    },
    "queues": {"high_potential_min_popularity": 16, "high_potential_min_total": 50, "technical_min_total": 35},
}
NON_PUBLISHER_EXCLUDED = {"ECOMMERCE", "CORPORATE", "SAAS", "MARKETPLACE", "GOVERNMENT", "PARKED_DOMAIN"}


@dataclass
class ScoreInput:
    excluded: bool
    exclusion_reason: str | None
    category: str | None
    secondary: list[str]
    is_publisher: bool | None
    classification_confidence: float
    crux_buckets: dict[str, int]  # country ("global" or ISO2) -> best bucket
    tranco_best: int | None
    bundle: EvidenceBundle
    opportunities: list[Opportunity]
    organization: str | None = None
    ads_txt_contact: bool = False
    ads_txt_owner_or_manager: bool = False
    seller_name_match: bool = False
    business_links: dict[str, str] = field(default_factory=dict)
    last_scan_at: dt.datetime | None = None


@dataclass
class ScoreResult:
    popularity: float
    ad_opportunity: float
    audience_geo: float
    inventory: float
    actionability: float
    evidence_quality: float
    total: float
    queue: str
    evidence_confidence: float
    explanation: dict[str, list[str]]
    missing_critical: list[str]
    next_action: str


def popularity_score(crux: dict[str, int], tranco: int | None, w: dict[str, Any] = DEFAULT_WEIGHTS) -> tuple[float, list[str]]:
    notes, pts = [], 0.0
    g = crux.get("global")
    if g:
        p = float(w["crux_bucket_points"].get(str(g), 3))
        pts = max(pts, p)
        notes.append(f"CrUX global top-{g:,} bucket (popularity band, not visits) -> {p:g}")
    if tranco:
        p = next((float(v) for lim, v in w["tranco_rank_points"] if tranco <= lim), 2.0)
        notes.append(f"Tranco rank {tranco:,} (ranking, not visits) -> {p:g}")
        pts = max(pts, p)
    return min(pts, w["max"]["popularity"]), notes


def audience_score(crux: dict[str, int], w: dict[str, Any] = DEFAULT_WEIGHTS) -> tuple[float, list[str], str | None]:
    best, notes, primary = 0.0, [], None
    base = {1000: 15, 5000: 14, 10000: 12, 50000: 10, 100000: 8, 500000: 6, 1000000: 5}
    for cc, bucket in crux.items():
        if cc == "global":
            continue
        tier = "1" if cc in w["geo_tiers"]["1"] else "2" if cc in w["geo_tiers"]["2"] else "other"
        p = base.get(bucket, 4) * w["geo_tier_multiplier"][tier]
        notes.append(f"Observed in CrUX {cc} top-{bucket:,} (tier {tier}) -> {p:.1f}")
        if p > best:
            best, primary = p, cc
    return min(best, w["max"]["audience_geo"]), notes, primary


def compute(inp: ScoreInput, w: dict[str, Any] = DEFAULT_WEIGHTS) -> ScoreResult:
    expl: dict[str, list[str]] = {k: [] for k in w["max"]}
    missing: list[str] = []

    pop, notes = popularity_score(inp.crux_buckets, inp.tranco_best, w)
    expl["popularity"] = notes or ["no CrUX/Tranco popularity observation -> 0"]
    if not notes:
        missing.append("popularity (CrUX/Tranco)")

    # ad opportunity
    ad = 0.0
    if inp.opportunities:
        vals = sorted((w["opportunity_base"][o.type] * min(1.0, o.confidence / 0.7), o) for o in inp.opportunities)
        ad = vals[-1][0] + min(3.0, 1.5 * (len([v for v in vals if v[1].type in "ABCDE"]) - 1)) if vals else 0.0
        for v, o in vals:
            expl["ad_opportunity"].append(f"{o.type} {o.label} (confidence {o.confidence:.2f}) -> {v:.1f}")
    else:
        expl["ad_opportunity"].append("no opportunity hypothesis -> 0")
    ad = min(ad, w["max"]["ad_opportunity"])

    geo, gnotes, _ = audience_score(inp.crux_buckets, w)
    expl["audience_geo"] = gnotes or ["no country-level CrUX observation; language/TLD alone is not used -> 0"]
    if not gnotes:
        missing.append("observed audience geography (CrUX country lists)")

    # inventory suitability
    inv = float(w["category_inventory_points"].get(inp.category or "", 0))
    expl["inventory"].append(f"category {inp.category} -> {inv:g}")
    types = (inp.bundle.inventory or {}).get("types", {})
    fmt_pts = 0.0
    for t, p in (("in_content", 2), ("sidebar", 1), ("sticky", 1.5), ("anchor", 1.5), ("header", 1)):
        if types.get(t):
            fmt_pts += p
            expl["inventory"].append(f"{t} placement observed -> +{p}")
    if (inp.bundle.inventory or {}).get("video"):
        fmt_pts += 1.5
        expl["inventory"].append("video ad integration observed -> +1.5")
    if not inp.bundle.inventory:
        missing.append("ad inventory profile (rendered scan)")
    inv = min(inv + fmt_pts, w["max"]["inventory"])

    # commercial actionability
    act = 0.0
    if inp.organization:
        act += 3
        expl["actionability"].append(f"publisher organisation identified: {inp.organization} -> +3")
    if inp.business_links.get("advertise"):
        act += 3
        expl["actionability"].append("advertising / media-kit page found -> +3")
    elif inp.business_links.get("contact"):
        act += 1.5
        expl["actionability"].append("contact page found -> +1.5")
    if inp.ads_txt_contact:
        act += 1.5
        expl["actionability"].append("ads.txt CONTACT declared -> +1.5")
    if inp.seller_name_match:
        act += 2.5
        expl["actionability"].append("sellers.json names the publisher on a DIRECT account -> +2.5")
    if act == 0:
        missing.append("publisher identity / business contact route")
    act = min(act, w["max"]["actionability"])

    # evidence quality
    eq = 0.0
    if inp.classification_confidence >= 0.7:
        eq += 1.5
    if inp.bundle.rendered_pages_ok:
        eq += 2
    if inp.bundle.ads_txt_status and inp.bundle.ads_txt_status != "FETCH_FAILED":
        eq += 1
    if inp.last_scan_at and (dt.datetime.now(dt.timezone.utc) - inp.last_scan_at).days <= 30:
        eq += 0.5
    expl["evidence_quality"].append(f"classification conf {inp.classification_confidence:.2f}, rendered pages {inp.bundle.rendered_pages_ok}, ads.txt {inp.bundle.ads_txt_status} -> {eq:g}")
    eq = min(eq, w["max"]["evidence_quality"])

    total = round(pop + ad + geo + inv + act + eq, 1)
    ev_conf = round(min(1.0, 0.4 * inp.classification_confidence + 0.4 * (1.0 if inp.bundle.rendered_pages_ok else 0.3)
                         + 0.2 * (1.0 if inp.bundle.ads_txt_status not in (None, "FETCH_FAILED") else 0.0)), 2)
    if not inp.bundle.rendered_pages_ok:
        missing.append("rendered ad-tech scan")

    queue, action = _queue(inp, total, pop, ad, w)
    return ScoreResult(round(pop, 1), round(ad, 1), round(geo, 1), round(inv, 1), round(act, 1), round(eq, 1), total,
                       queue, ev_conf, expl, missing, action)


def _queue(inp: ScoreInput, total: float, pop: float, ad: float, w: dict[str, Any]) -> tuple[str, str]:
    q = w["queues"]
    if inp.excluded:
        return "EXCLUDED", f"Excluded: {inp.exclusion_reason}"
    if inp.category in NON_PUBLISHER_EXCLUDED and "GENERAL_CONTENT_PUBLISHER" not in (inp.secondary or []):
        return "EXCLUDED", f"Not an advertising-supported publisher ({inp.category})."
    types = {o.type for o in inp.opportunities}
    if inp.category in (None, "UNKNOWN", "OTHER") or inp.classification_confidence < 0.5:
        return "NEEDS_REVIEW", "Classify manually (automatic classification uncertain)."
    inconclusive = inp.bundle.vendors.get("google_gam", {}).get("status") == INCONCLUSIVE
    if inconclusive or types <= {"F", "G"} and types:
        return "NEEDS_REVIEW", "Inspect the site manually; ad-tech evidence is inconclusive or business model unclear."
    strong = types & set("ABCDE")
    if strong and pop >= q["high_potential_min_popularity"] and total >= q["high_potential_min_total"]:
        # VERIFIED_HIGH_VALUE requires verified traffic: assigned only by manual override after research.
        return "HIGH_POTENTIAL_VERIFY_TRAFFIC", "Research traffic manually; if confirmed, promote to VERIFIED_HIGH_VALUE and find a contact."
    if strong and total >= q["technical_min_total"]:
        return "TECHNICAL_OPPORTUNITY", "Technical opportunity on a less popular site; check traffic before investing time."
    return "LOW_PRIORITY", "Monitor; no strong opportunity or popularity signal."


def any_active(bundle: EvidenceBundle) -> bool:
    return any(v["status"] == ACTIVE for v in bundle.vendors.values())
