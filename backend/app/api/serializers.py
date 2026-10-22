from __future__ import annotations

from typing import Any

from app.models import Website

EXPLORER_COLUMNS = [
    "id", "host", "registrable_domain", "primary_category", "is_publisher", "classification_confidence", "primary_geo",
    "country_signals", "language", "crux_best_bucket", "tranco_best_rank", "monetization_type", "gam_status", "adsense_status",
    "prebid_status", "observed_partners", "declared_ad_systems_count", "opportunity_types", "score_total", "queue",
    "evidence_confidence", "contact_status", "last_analyzed_at", "outreach_stage", "excluded", "exclusion_reason",
    "first_discovered_at", "discovery_priority",
]


def website_row(w: Website) -> dict[str, Any]:
    out = {}
    for c in EXPLORER_COLUMNS:
        v = getattr(w, c)
        out[c] = v.isoformat() if hasattr(v, "isoformat") else v
    return out
