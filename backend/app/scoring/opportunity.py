"""Monetization opportunity engine.

Converts evidence (classification, ad-tech statuses, inventory, ads.txt, popularity) into
opportunity hypotheses A-G. Every hypothesis lists its evidence, confidence, what is missing
and how to verify it. Nothing here asserts revenue, fill, impressions or contracts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.adtech.detector import ACTIVE, DECLARED, INCONCLUSIVE, NOT_OBSERVED, POSSIBLE

ENGINE_VERSION = "opportunity-1.0"
PRESENT = (ACTIVE, POSSIBLE)

LABELS = {
    "A": "AdSense-focused publisher",
    "B": "GAM without observed header bidding",
    "C": "Limited observed header bidding competition",
    "D": "Possibly underutilised ad inventory",
    "E": "Existing monetization partner",
    "F": "Popular site, no advertising observed",
    "G": "Insufficient evidence",
}


@dataclass
class Opportunity:
    type: str
    confidence: float
    evidence: list[dict[str, Any]]
    hypothesis: str
    missing: list[str]
    verification: str
    approach: str
    label: str = ""

    def __post_init__(self) -> None:
        self.label = LABELS[self.type]


@dataclass
class EvidenceBundle:
    is_publisher: bool | None
    category: str | None
    classification_confidence: float
    vendors: dict[str, dict[str, Any]]  # vendor_key -> {status, confidence, category, name, detail}
    rendered_pages_ok: int
    static_pages_ok: int
    adtech_scanned: bool
    ads_txt_status: str | None
    ads_txt_record_count: int
    ads_txt_systems: list[str]
    inventory: dict[str, Any] = field(default_factory=dict)
    popularity_points: float = 0.0  # 0..30 from scoring.popularity_score
    article_word_counts: list[int] = field(default_factory=list)


def _st(b: EvidenceBundle, key: str) -> str | None:
    v = b.vendors.get(key)
    return v["status"] if v else None


def _ev(b: EvidenceBundle, key: str) -> dict[str, Any]:
    v = b.vendors.get(key) or {}
    return {"vendor": key, "status": v.get("status"), "confidence": v.get("confidence")}


def assess(b: EvidenceBundle) -> list[Opportunity]:
    out: list[Opportunity] = []
    if b.is_publisher is False:
        return out

    gam, adsense, prebid, aps = (_st(b, k) for k in ("google_gam", "google_adsense", "prebid", "amazon_aps"))
    openwrap = _st(b, "pubmatic_openwrap")
    managed = sorted(k for k, v in b.vendors.items() if v.get("category") == "monetization_partner" and v["status"] in PRESENT)
    ssps_active = sorted(k for k, v in b.vendors.items() if v.get("category") in ("ssp", "native") and v["status"] == ACTIVE)
    gam_detail = (b.vendors.get("google_gam") or {}).get("detail") or {}
    pb_detail = (b.vendors.get("prebid") or {}).get("detail") or {}
    rendered = b.rendered_pages_ok > 0
    hb_present = prebid in PRESENT or aps == ACTIVE or openwrap in PRESENT

    if not b.adtech_scanned or (b.rendered_pages_ok == 0 and b.static_pages_ok == 0):
        out.append(Opportunity(
            "G", 0.3, [{"signal": "ad-tech scan not completed or inconclusive"}],
            "Promising site whose advertising stack could not be inspected.",
            ["rendered ad-tech scan", "ads.txt"],
            "Re-run the ad-tech scan; if the site blocks automated browsers, inspect manually in a normal browser.",
            "Decide after manual inspection.",
        ))
        return out

    # ---------------- A: AdSense-focused
    if adsense in PRESENT and gam not in PRESENT and not hb_present and not managed:
        conf = 0.75 if (rendered and adsense == ACTIVE) else 0.45
        miss = [] if rendered else ["rendered scan (static HTML only)"]
        out.append(Opportunity(
            "A", conf, [_ev(b, "google_adsense"), _ev(b, "google_gam"), _ev(b, "prebid")],
            "Advertising appears to run mainly through AdSense with no ad server or header bidding observed on inspected pages.",
            miss + ["page RPM / revenue (publisher-provided)", "whether other demand runs on unsampled pages"],
            "Confirm on several article pages in a normal browser that only AdSense units load; ask publisher about current setup.",
            "Introduce GAM with Prebid header bidding and additional SSP demand alongside AdSense/AdX.",
        ))

    # ---------------- B: GAM without observed HB
    if gam == ACTIVE and not hb_present:
        if prebid == NOT_OBSERVED and rendered:
            conf = 0.7 if b.rendered_pages_ok >= 2 else 0.6
            ev = [_ev(b, "google_gam"), _ev(b, "prebid"), _ev(b, "amazon_aps")]
            if gam_detail.get("network_codes"):
                ev.append({"signal": "GAM network code(s)", "value": gam_detail["network_codes"]})
            note = ""
            if gam_detail.get("mcm_child_networks"):
                note = " GAM ad unit paths use MCM (parent,child) - inventory may be managed through a partner network."
                ev.append({"signal": "MCM child network(s)", "value": gam_detail["mcm_child_networks"]})
            out.append(Opportunity(
                "B", conf, ev,
                "Google Ad Manager is running but no client-side header bidding was observed on rendered pages." + note,
                ["server-side bidding (not visible client-side)", "Open Bidding / AdX configuration in GAM"],
                "Check GAM ad requests for Open Bidding/server-side parameters; confirm with publisher whether header bidding is used.",
                "Add Prebid.js header bidding with Purify demand partners competing against AdX in GAM.",
            ))

    # ---------------- C: limited HB competition
    if prebid == ACTIVE:
        bidders = set(pb_detail.get("configured_bidders", [])) | set(pb_detail.get("requested_bidders", []))
        s2s = set(pb_detail.get("s2s_bidders", []))
        if 0 < len(bidders) <= 4:
            out.append(Opportunity(
                "C", 0.6 if not s2s else 0.45,
                [{"signal": "Prebid client-side bidders observed", "value": sorted(bidders)},
                 {"signal": "Prebid server-side bidders", "value": sorted(s2s)}],
                f"Prebid is running with only {len(bidders)} identifiable client-side bidder(s).",
                ["bidders on unsampled pages / geos", "server-side or GAM-side demand"],
                "Inspect pbjs.getEvents() on several pages and geos; compare against ads.txt authorised sellers.",
                "Add incremental bidders (Purify demand) into the existing Prebid setup or via Purify's wrapper.",
            ))
        elif not bidders:
            out.append(Opportunity(
                "C", 0.35, [{"signal": "Prebid present but bidders not readable from page state"}],
                "Prebid is present, but its bidders could not be enumerated from the rendered page.",
                ["bidder list"], "Inspect the Prebid configuration manually in DevTools.",
                "Evaluate adding bidders once the current set is known.",
            ))

    # ---------------- D: possibly underutilised inventory
    inv = b.inventory or {}
    placements = inv.get("placements_per_page")
    long_articles = [w for w in b.article_word_counts if w >= 700]
    if (gam in PRESENT or adsense in PRESENT) and long_articles and placements is not None:
        if placements <= 2 or not inv.get("types", {}).get("in_content"):
            out.append(Opportunity(
                "D", 0.4,
                [{"signal": "long-form article pages sampled", "value": long_articles},
                 {"signal": "ad placements per sampled page", "value": placements},
                 {"signal": "in-content placements observed", "value": inv.get("types", {}).get("in_content", 0)}],
                "Content-heavy pages show few observed ad placements; there may be room for additional formats (hypothesis only).",
                ["lazy-loaded slots below sampled depth", "publisher UX / ad-density policy", "viewability data"],
                "Scroll full article pages manually; review ad density against Better Ads standards.",
                "Propose in-content, sticky/anchor and video formats with viewability-aware lazy loading.",
            ))

    # ---------------- E: existing monetization partner
    if managed or gam_detail.get("mcm_child_networks"):
        ev = [_ev(b, k) for k in managed]
        if gam_detail.get("mcm_child_networks"):
            ev.append({"signal": "GAM MCM child network", "value": gam_detail["mcm_child_networks"]})
        out.append(Opportunity(
            "E", 0.6 if any((b.vendors.get(k) or {}).get("status") == ACTIVE for k in managed) else 0.45, ev,
            "The site appears to work with an identifiable monetization company or managed network.",
            ["contract terms / exclusivity", "partner's demand stack"],
            "Identify the partner relationship (ads.txt MANAGERDOMAIN, MCM) and whether non-exclusive demand is accepted.",
            "Offer incremental demand or an alternative integration; consider partnership with the incumbent where competing is unrealistic.",
        ))

    # ---------------- F: popular, nothing observed
    key = [gam, adsense, prebid, aps]
    if rendered and all(s == NOT_OBSERVED for s in key) and not ssps_active and not managed and b.ads_txt_record_count == 0 and b.popularity_points >= 16:
        out.append(Opportunity(
            "F", 0.5, [{"signal": "rendered pages without any observed ad technology"}, {"signal": "no ads.txt records"}],
            "Popular site with no observable advertising integrations - business model and ad policy unknown.",
            ["business model (subscription / ad-free policy)", "decision maker"],
            "Investigate business model and whether the publisher accepts advertising before any outreach.",
            "Only if ads are acceptable: full GAM + Prebid setup. Do not treat as immediately monetizable.",
        ))

    # ---------------- G: inconclusive scan of a promising site
    if not out and (b.rendered_pages_ok == 0 or any(s == INCONCLUSIVE for s in key)):
        out.append(Opportunity(
            "G", 0.3, [{"signal": "rendered scan unavailable or inconclusive"}],
            "Potentially promising publisher needing further technical investigation.",
            ["rendered ad-tech scan"], "Re-scan or inspect manually.", "Decide after investigation.",
        ))
    return out


def declared_only_count(vendors: dict[str, dict[str, Any]]) -> int:
    return sum(1 for v in vendors.values() if v["status"] == DECLARED)
