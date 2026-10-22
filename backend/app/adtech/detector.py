"""Evidence-based ad-tech detection.

Turns raw observations (static HTML, script URLs, rendered-page network requests, JS globals,
Prebid/GPT runtime state, ads.txt records) into per-vendor conclusions with one of five statuses:

DETECTED_ACTIVE_SIGNALS     runtime evidence the integration executes on the page: a vendor
                            ad/bid request was observed on the network, a vendor JS object was
                            initialised, or the vendor is a configured/requested Prebid bidder.
                            NOT proof of auctions won, fill, revenue or a commercial agreement.
DECLARED_AUTHORIZATION_ONLY the vendor appears only in ads.txt (authorisation to sell), with no
                            on-page evidence.
POSSIBLE                    static-only or weak evidence (script reference / inline pattern in
                            un-rendered HTML).
NOT_OBSERVED                pages were scanned successfully and nothing was found. Confidence is
                            lower when only static HTML (no rendering) was available.
SCAN_INCONCLUSIVE           scans failed / were blocked; absence cannot be inferred.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.adtech.registry import Registry, Vendor, load_registry

ENGINE_VERSION = "adtech-1.0"

ACTIVE = "DETECTED_ACTIVE_SIGNALS"
DECLARED = "DECLARED_AUTHORIZATION_ONLY"
POSSIBLE = "POSSIBLE"
NOT_OBSERVED = "NOT_OBSERVED"
INCONCLUSIVE = "SCAN_INCONCLUSIVE"

# Always reported, even when absent, because the opportunity engine reasons about them.
KEY_VENDORS = ("google_gam", "google_adsense", "prebid", "amazon_aps")

_SCRIPT_SRC_RE = re.compile(r"<script[^>]+src\s*=\s*[\"']([^\"']+)[\"']", re.I)
_LINK_HREF_RE = re.compile(r"<link[^>]+href\s*=\s*[\"']([^\"']+)[\"']", re.I)
_GAM_PATH_RE = re.compile(r"""defineSlot\(\s*['"](/[0-9,]+/[^'"]*)['"]""")
_ADSENSE_CLIENT_RE = re.compile(r"ca-pub-(\d{10,20})")


@dataclass
class PageObservation:
    url: str
    role: str = "homepage"
    ok: bool = True
    rendered: bool = False
    html: str = ""
    script_urls: list[str] = field(default_factory=list)
    network_urls: list[str] = field(default_factory=list)
    globals_present: dict[str, bool] = field(default_factory=dict)
    prebid: list[dict[str, Any]] = field(default_factory=list)  # one entry per pbjs instance
    gpt: dict[str, Any] | None = None  # {"slots": [{path, sizes, div}], "pubads_ready": bool}
    consent: dict[str, Any] | None = None  # CMP state captured in rendered pages (see render.py)
    blocked_reason: str | None = None


@dataclass
class AdsTxtObservation:
    status: str  # FOUND | NOT_FOUND | ... | FETCH_FAILED
    records: list[dict[str, Any]] = field(default_factory=list)  # ad_system_domain, seller_account_id, relationship


@dataclass
class Evidence:
    kind: str
    value: str
    page_url: str | None = None
    observation: str = "OBSERVED"

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value[:500], "page_url": self.page_url, "observation": self.observation}


@dataclass
class VendorResult:
    vendor_key: str
    vendor_name: str
    category: str
    status: str
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def extract_script_urls(html: str) -> list[str]:
    urls = [m.group(1) for m in _SCRIPT_SRC_RE.finditer(html or "")]
    urls += [m.group(1) for m in _LINK_HREF_RE.finditer(html or "") if "preload" in m.group(0).lower() or ".js" in m.group(1)]
    return urls


def _add(ev: dict[str, list[Evidence]], key: str, e: Evidence) -> None:
    lst = ev.setdefault(key, [])
    if len(lst) < 25 and not any(x.kind == e.kind and x.value == e.value for x in lst):
        lst.append(e)


def detect(
    pages: list[PageObservation],
    ads_txt: AdsTxtObservation | None = None,
    registry: Registry | None = None,
) -> list[VendorResult]:
    reg = registry or load_registry()
    strong: dict[str, list[Evidence]] = {}
    weak: dict[str, list[Evidence]] = {}
    declared: dict[str, list[Evidence]] = {}
    details: dict[str, dict[str, Any]] = {}

    ok_static = [p for p in pages if p.ok and not p.rendered]
    ok_rendered = [p for p in pages if p.ok and p.rendered]

    for page in pages:
        if not page.ok:
            continue
        script_urls = list(page.script_urls) or extract_script_urls(page.html)
        for v in reg.vendors:
            # script references
            for url in script_urls:
                if any(p.search(url) for p in v.script):
                    target = strong if (page.rendered and v.globals == [] and not v.network) else weak
                    _add(target, v.key, Evidence("script_url", url, page.url))
            # network requests (rendered only)
            for url in page.network_urls:
                if any(p.search(url) for p in v.network):
                    _add(strong, v.key, Evidence("network_request", url, page.url))
                elif page.rendered and any(p.search(url) for p in v.script):
                    _add(weak, v.key, Evidence("script_url", url, page.url))
            # globals
            for g in v.globals:
                if page.globals_present.get(g):
                    _add(strong, v.key, Evidence("js_global", g, page.url))
            # static html patterns (skip for rendered pages where better evidence exists)
            if page.html and v.html:
                for p in v.html:
                    m = p.search(page.html)
                    if m:
                        _add(weak, v.key, Evidence("html", m.group(0)[:200], page.url))
                        break

        # ---- Prebid runtime state
        for inst in page.prebid or []:
            name = inst.get("global", "pbjs")
            _add(strong, "prebid", Evidence("js_global", f"{name} v{inst.get('version')}", page.url))
            d = details.setdefault("prebid", {"instances": [], "configured_bidders": set(), "requested_bidders": set(), "responding_bidders": set()})
            d["instances"].append({"global": name, "version": inst.get("version"), "page": page.url})
            for code in inst.get("configured_bidders", []):
                d["configured_bidders"].add(code)
            for code in inst.get("requested_bidders", []):
                d["requested_bidders"].add(code)
            for code in inst.get("responding_bidders", []):
                d["responding_bidders"].add(code)
            if inst.get("s2s_bidders"):
                d.setdefault("s2s_bidders", set()).update(inst["s2s_bidders"])
            for code in set(inst.get("configured_bidders", [])) | set(inst.get("requested_bidders", [])):
                vk = reg.vendor_for_bidder(code)
                kind = "prebid_bid_requested" if code in inst.get("requested_bidders", []) else "prebid_config"
                if vk:
                    _add(strong, vk, Evidence(kind, f"bidder '{code}'", page.url))
                else:
                    details.setdefault("prebid", {}).setdefault("unmapped_bidders", set()).add(code)

        # ---- GPT runtime state
        if page.gpt and page.gpt.get("slots"):
            slots = page.gpt["slots"]
            _add(strong, "google_gam", Evidence("gpt_slot", f"{len(slots)} slot(s) defined", page.url))
            d = details.setdefault("google_gam", {"ad_unit_paths": set(), "network_codes": set(), "mcm_child_networks": set()})
            for s in slots:
                path = s.get("path") or ""
                d["ad_unit_paths"].add(path)
                _parse_gam_path(path, d)
        # static defineSlot paths
        for m in _GAM_PATH_RE.finditer(page.html or ""):
            d = details.setdefault("google_gam", {"ad_unit_paths": set(), "network_codes": set(), "mcm_child_networks": set()})
            d["ad_unit_paths"].add(m.group(1))
            _parse_gam_path(m.group(1), d)
        for m in _ADSENSE_CLIENT_RE.finditer(page.html or ""):
            details.setdefault("google_adsense", {"publisher_ids": set()})["publisher_ids"].add("ca-pub-" + m.group(1))

    # ---- ads.txt (declared authorisation)
    ads_ok = ads_txt is not None and ads_txt.status in ("FOUND", "NOT_FOUND", "EMPTY", "NOT_TEXT")
    if ads_txt and ads_txt.records:
        per_vendor: dict[str, dict[str, set]] = {}
        for r in ads_txt.records:
            vk = reg.vendor_for_ad_system(r["ad_system_domain"])
            if not vk:
                continue
            pv = per_vendor.setdefault(vk, {"DIRECT": set(), "RESELLER": set()})
            pv[r["relationship"]].add(r["seller_account_id"])
        for vk, rel in per_vendor.items():
            _add(declared, vk, Evidence("ads_txt", f"DIRECT={len(rel['DIRECT'])} RESELLER={len(rel['RESELLER'])}", None, "DECLARED"))
            details.setdefault(vk, {})["ads_txt"] = {"direct_accounts": sorted(rel["DIRECT"])[:20], "reseller_accounts": sorted(rel["RESELLER"])[:20]}

    # ---- consent context (EU cookie walls)
    accepted = [p for p in ok_rendered if (p.consent or {}).get("accepted_by_robot")]
    consent_note = None
    if accepted:
        cmps = sorted({c for p in accepted for c in ((p.consent or {}).get("cmps") or [])})
        consent_note = f"observed after the robot accepted the cookie banner ({', '.join(cmps) or 'CMP'})"

    # ---- resolve statuses
    results: list[VendorResult] = []
    for v in reg.vendors:
        s, w, dcl = strong.get(v.key, []), weak.get(v.key, []), declared.get(v.key, [])
        detail = _jsonable(details.get(v.key, {}))
        if s:
            conf = 0.9 if any(e.kind in ("network_request", "prebid_bid_requested", "gpt_slot") for e in s) else 0.8
            results.append(VendorResult(v.key, v.name, v.category, ACTIVE, conf, s + w + dcl, detail))
        elif w:
            conf = 0.55 if any(e.kind == "script_url" for e in w) else 0.4
            results.append(VendorResult(v.key, v.name, v.category, POSSIBLE, conf, w + dcl, detail))
        elif dcl:
            results.append(VendorResult(v.key, v.name, v.category, DECLARED, 0.5, dcl, detail))
        elif v.key in KEY_VENDORS:
            results.append(_absence(v, ok_static, ok_rendered, ads_ok, pages))
    if consent_note:
        for r in results:
            if r.status in (ACTIVE, NOT_OBSERVED) and r.category not in ("cms", "analytics", "forum_software", "ecommerce_platform"):
                r.detail = {**r.detail, "consent": consent_note}
    return results


def _consent_gated(ok_rendered: list[PageObservation]) -> list[str]:
    """CMP names if every successfully rendered page was still waiting for cookie consent."""
    if not ok_rendered or not all((p.consent or {}).get("pending") for p in ok_rendered):
        return []
    names: set[str] = set()
    for p in ok_rendered:
        names.update((p.consent or {}).get("cmps") or [])
    return sorted(names) or ["unidentified CMP"]


def _absence(v: Vendor, ok_static, ok_rendered, ads_ok, pages) -> VendorResult:
    gated = _consent_gated(ok_rendered)
    if gated:
        # Ads on consent-walled pages typically load only after "Accept"; absence proves nothing.
        return VendorResult(v.key, v.name, v.category, INCONCLUSIVE, 0.0,
                            detail={"reasons": [f"ads likely waiting for cookie consent ({', '.join(gated)})"],
                                    "scan_depth": "rendered", "consent_gated": True})
    if ok_rendered:
        return VendorResult(v.key, v.name, v.category, NOT_OBSERVED, 0.6,
                            detail={"scan_depth": "rendered", "pages_rendered": len(ok_rendered)})
    if ok_static and not v.needs_render:
        return VendorResult(v.key, v.name, v.category, NOT_OBSERVED, 0.45, detail={"scan_depth": "static"})
    if ok_static:
        return VendorResult(v.key, v.name, v.category, NOT_OBSERVED, 0.3,
                            detail={"scan_depth": "static_only", "note": "dynamic loaders are invisible without rendering"})
    reasons = sorted({p.blocked_reason for p in pages if p.blocked_reason})
    return VendorResult(v.key, v.name, v.category, INCONCLUSIVE, 0.0, detail={"reasons": reasons})


def _parse_gam_path(path: str, d: dict[str, Any]) -> None:
    m = re.match(r"^/(\d+)(?:,(\d+))?/", path or "")
    if m:
        d["network_codes"].add(m.group(1))
        if m.group(2):
            # "/parent,child/" = Multiple Customer Management: inventory managed via a partner network
            d["mcm_child_networks"].add(m.group(2))


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (set, tuple)):
        return sorted(_jsonable(x) for x in obj)
    if isinstance(obj, list):
        return [_jsonable(x) for x in obj]
    return obj


def summarize(results: list[VendorResult]) -> dict[str, Any]:
    """Compact summary used by the opportunity engine and explorer."""
    by = {r.vendor_key: r for r in results}
    ad = [r for r in results if r.category in ("ssp", "header_bidding", "native", "video", "monetization_partner", "ad_server", "adsense")]
    observed_partners = sorted(r.vendor_key for r in ad if r.status == ACTIVE and r.vendor_key not in ("google_gam", "google_adsense", "prebid"))
    declared_only = sorted(r.vendor_key for r in results if r.status == DECLARED)
    prebid_detail = by.get("prebid").detail if by.get("prebid") else {}
    return {
        "gam": by["google_gam"].status if "google_gam" in by else None,
        "adsense": by["google_adsense"].status if "google_adsense" in by else None,
        "prebid": by["prebid"].status if "prebid" in by else None,
        "aps": by["amazon_aps"].status if "amazon_aps" in by else None,
        "observed_partners": observed_partners,
        "managed_partners": sorted(r.vendor_key for r in results if r.category == "monetization_partner" and r.status in (ACTIVE, POSSIBLE)),
        "declared_only": declared_only,
        "prebid_bidders": sorted(set(prebid_detail.get("configured_bidders", [])) | set(prebid_detail.get("requested_bidders", []))),
        "gam_mcm": bool(by.get("google_gam") and by["google_gam"].detail.get("mcm_child_networks")),
        "cms": sorted(r.vendor_key for r in results if r.category == "cms" and r.status in (ACTIVE, POSSIBLE)),
    }
