"""Pipeline stages. Each stage reads stored observations, writes new observations/conclusions,
and never deletes evidence from earlier stages. Conclusions are replaced only when the new
run produced usable evidence (a failed scan keeps the previous conclusion current)."""
from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import hashlib
import logging
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.adtech import detector
from app.adtech.detector import AdsTxtObservation, PageObservation
from app.adtech.registry import load_registry
from app.classify import features as feat
from app.classify import rules
from app.core.config import get_settings
from app.core.db import session_scope
from app.models import (
    AdInventory, AdsTxtFile, AdsTxtRecord, DetectedTechnology, ManualOverride, OpportunityAssessment, Organization,
    PopularityObservation, Scan, ScanPage, Score, SellerEntity, TechnologyEvidence, Website, WebsiteClassification,
    WebsiteSource,
)
from app.pipeline import claims
from app.pipeline.exclusions import check as check_exclusion
from app.pipeline.exclusions import load_rules
from app.scoring import opportunity as opp
from app.scoring import score as scoring
from app.services.normalize import same_site, try_normalize
from app.services.safe_fetch import FetchResult, SafeFetcher
from app.services.settings_store import get_setting
from app.supply import adstxt

log = logging.getLogger(__name__)
HTML_TYPES = ("text/html", "application/xhtml")
MAX_STORED_HTML = 1_500_000


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _gz(text: str) -> bytes:
    return gzip.compress(text[:MAX_STORED_HTML].encode("utf-8", errors="replace"), compresslevel=6)


def _ungz(b: bytes | None) -> str:
    return gzip.decompress(b).decode("utf-8", errors="replace") if b else ""


# =================================================================== QUALIFY (no network)
def run_qualify(ids: list[int]) -> None:
    """Set-based: one query per batch for popularity and sources; no per-site summary refresh."""
    from app.services.summary import refresh_popularity_columns

    qcfg = get_setting("qualification")
    with session_scope() as db:
        rules_ = load_rules(db)
        sites = db.execute(select(Website.id, Website.host, Website.registrable_domain, Website.excluded, Website.exclusion_reason,
                                  Website.discovery_priority).where(Website.id.in_(ids))).all()
        pops = _popularity_many(db, ids)
        manual_ids = set(db.scalars(select(WebsiteSource.website_id).where(
            WebsiteSource.website_id.in_(ids), WebsiteSource.source_type.in_(("manual", "csv", "legacy")))))
        newly_excluded: list[tuple[int, str]] = []
        for wid, host, reg_dom, excluded, ex_reason, prio in sites:
            if excluded:
                claims.complete(db, wid, "qualify", "SKIPPED", {"reason": "excluded", "detail": ex_reason}, advance=False)
                continue
            dec = check_exclusion(host, reg_dom, rules_)
            if dec.excluded:
                newly_excluded.append((wid, dec.reason))
                claims.complete(db, wid, "qualify", "SKIPPED", {"reason": "excluded", "detail": dec.reason}, advance=False)
                continue
            crux, tranco = pops.get(wid, ({}, None))
            manual = wid in manual_ids
            g = crux.get("global")
            popular = bool((g and g <= qcfg["max_crux_bucket"]) or (tranco and tranco <= qcfg["max_tranco_rank"])
                           or any(b <= qcfg["max_country_crux_bucket"] for c, b in crux.items() if c != "global"))
            if popular or manual:
                claims.complete(db, wid, "qualify", "DONE",
                                {"reason": "manual source" if manual and not popular else "popularity", "crux": crux, "tranco": tranco},
                                next_priority=prio)
            else:
                claims.complete(db, wid, "qualify", "SKIPPED", {"reason": "insufficient_popularity", "crux": crux, "tranco": tranco},
                                advance=False)
        for wid, reason in newly_excluded:
            db.execute(update(Website).where(Website.id == wid).values(excluded=True, exclusion_reason=reason))
        refresh_popularity_columns(db, ids)


def _popularity_many(db: Session, ids: list[int]) -> dict[int, tuple[dict[str, int], int | None]]:
    rows = db.execute(select(PopularityObservation.website_id, PopularityObservation.source, PopularityObservation.country,
                             PopularityObservation.period, PopularityObservation.rank_bucket, PopularityObservation.rank)
                      .where(PopularityObservation.website_id.in_(ids))).all()
    by: dict[int, list] = {}
    for r in rows:
        by.setdefault(r[0], []).append(r[1:])
    out = {}
    for wid, obs in by.items():
        out[wid] = _reduce_popularity(obs)
    return out


def _reduce_popularity(obs) -> tuple[dict[str, int], int | None]:
    latest: dict[str, str] = {}
    for src, c, p, _b, _r in obs:
        if src == "crux":
            latest[c] = max(latest.get(c, p), p)
    crux: dict[str, int] = {}
    for src, c, p, b, _r in obs:
        if src == "crux" and p == latest[c] and b:
            crux[c] = min(crux.get(c, b), b)
    tr = [(p, r) for src, _c, p, _b, r in obs if src == "tranco" and r]
    tranco = None
    if tr:
        lp = max(p for p, _ in tr)
        tranco = min(r for p, r in tr if p == lp)
    return crux, tranco


def _popularity(db: Session, wid: int) -> tuple[dict[str, int], int | None]:
    """Best CrUX bucket per country (latest period per country) and best Tranco rank (latest list)."""
    return _popularity_many(db, [wid]).get(wid, ({}, None))


# =================================================================== CLASSIFY (static HTTP)
async def _fetch_site_pages(fetcher: SafeFetcher, w: Website, max_pages: int) -> tuple[list[FetchResult], list[dict[str, Any]], str | None]:
    """Homepage + sampled content pages. Returns (results, features, problem)."""
    host = urlsplit(w.preferred_origin).hostname or w.host
    candidates = [f"https://{host}/", f"http://{host}/"]
    if not host.startswith("www.") and host == w.registrable_domain:
        candidates.insert(1, f"https://www.{host}/")
    results: list[FetchResult] = []
    home: FetchResult | None = None
    for url in candidates:
        r = await fetcher.get(url)
        results.append(r)
        if r.ok or r.blocked:
            home = r
            break
    if home is None or not home.ok:
        prob = (home.blocked if home else None) or (results[-1].error if results else "no response") or f"HTTP {results[-1].status}"
        return results, [], prob
    ctype = (home.content_type or "").lower()
    if not any(t in ctype for t in HTML_TYPES):
        return results, [], f"homepage is not HTML ({ctype})"
    home_f = feat.extract_safe(home.text(), home.final_url)
    feats = [home_f]
    final_host = urlsplit(home.final_url).hostname or host
    for u in home_f.get("article_link_sample", [])[: max(0, max_pages - 1)]:
        if urlsplit(u).hostname not in (final_host, host):
            continue
        r = await fetcher.get(u)
        results.append(r)
        if r.ok and any(t in (r.content_type or "").lower() for t in HTML_TYPES):
            feats.append(feat.extract_safe(r.text(), r.final_url))
    return results, feats, None


def _store_scan(db: Session, wid: int, kind: str, method: str, status: str, error: str | None,
                pages: list[dict[str, Any]], meta: dict | None = None) -> Scan:
    scan = Scan(website_id=wid, kind=kind, method=method, status=status, error=error, finished_at=_now(), meta=meta)
    for p in pages:
        scan.pages.append(ScanPage(**p))
    db.add(scan)
    db.flush()
    return scan


def _page_row(r: FetchResult, role: str) -> dict[str, Any]:
    is_html = any(t in (r.content_type or "").lower() for t in HTML_TYPES)
    body = r.text() if (r.body and is_html) else ""
    return {
        "url": r.url, "final_url": r.final_url, "page_role": role, "http_status": r.status, "content_type": (r.content_type or "")[:120],
        "html_sha256": hashlib.sha256(r.body).hexdigest() if r.body else None, "html_gz": _gz(body) if body else None,
        "script_urls": detector.extract_script_urls(body)[:300] if body else None,
        "blocked_reason": (r.blocked or r.error or (f"HTTP {r.status}" if r.status and r.status >= 400 else None)),
    }


def run_classify(ids: list[int]) -> None:
    asyncio.run(_classify_batch(ids))


async def _classify_batch(ids: list[int]) -> None:
    s = get_settings()
    with session_scope() as db:
        sites = [db.get(Website, i) for i in ids]
    sem = asyncio.Semaphore(16)

    async def one(w: Website):
        async with sem:
            try:
                return w, await _fetch_site_pages(fetcher, w, s.classification_max_pages), None
            except Exception as exc:  # noqa: BLE001
                return w, None, exc

    async with SafeFetcher() as fetcher:
        outcomes = await asyncio.gather(*(one(w) for w in sites if w))
    for w, res, exc in outcomes:
        if exc is not None:
            claims.fail(w.id, "classify", f"{type(exc).__name__}: {exc}")
            continue
        try:
            _persist_classification(w.id, *res)
        except Exception as e:  # noqa: BLE001
            log.exception("persist classification failed for %s", w.host)
            claims.fail(w.id, "classify", f"persist: {type(e).__name__}: {e}")


def _persist_classification(wid: int, results: list[FetchResult], feats: list[dict[str, Any]], problem: str | None) -> None:
    fail_msg: str | None = None
    with session_scope() as db:
        w = db.get(Website, wid)
        page_rows = [_page_row(r, "homepage" if (urlsplit(r.url).path in ("", "/")) else "article") for r in results]
        status = "OK" if feats else ("ROBOTS_DISALLOWED" if problem and "robots" in problem else
                                     "BLOCKED" if problem and ("challenge" in problem or "HTTP 403" in problem) else "FAILED")
        scan = _store_scan(db, wid, "http_fetch", "httpx", status, problem, page_rows)

        # redirects to another site: link and stop here (the destination is registered separately)
        if feats:
            final_host = urlsplit(feats[0]["url"]).hostname or ""
            if final_host and not same_site(final_host, w.host):
                dest, _ = try_normalize(final_host)
                w.canonical_host = final_host
                if dest:
                    from app.services.registry import Discovered, register
                    register(db, [Discovered(norm=dest, source_type="redirect", source_ref=f"redirect_from:{w.host}", priority=w.discovery_priority)])
                    dest_id = db.scalar(select(Website.id).where(Website.host == dest.host))
                    w.redirects_to_website_id = dest_id
                claims.complete(db, wid, "classify", "SKIPPED", {"reason": "redirects_to_other_site", "to": final_host}, advance=False)
                _refresh_summary(db, wid)
                return
            elif final_host:
                fp = urlsplit(feats[0]["url"])
                w.canonical_host = final_host
                w.preferred_origin = f"{fp.scheme or 'https'}://{final_host}"

        res = rules.classify(w.host, feats, fetch_ok=bool(feats), blocked_reason=problem)
        has_previous = db.scalar(select(func.count()).select_from(WebsiteClassification).where(
            WebsiteClassification.website_id == wid, WebsiteClassification.is_current.is_(True)))
        usable = res.primary_category != "UNKNOWN" or not has_previous
        if usable:
            db.execute(update(WebsiteClassification).where(WebsiteClassification.website_id == wid,
                                                           WebsiteClassification.is_current.is_(True)).values(is_current=False))
            rec = rules.as_record(res)
            home = feats[0] if feats else {}
            rec["features"] = {
                "scores": res.scores,
                "home": {k: home.get(k) for k in ("title", "description", "og_site_name", "html_lang", "schema_types", "feed_links",
                                                  "article_link_count", "article_link_sample", "business_links", "org_names", "tech",
                                                  "word_count", "topic_hits")},
                "pages": [{"url": f.get("url"), "word_count": f.get("word_count"), "schema_types": f.get("schema_types"),
                           "has_published_time": f.get("has_published_time")} for f in feats],
                "country_signals": feat.country_signals(feats, w.host),
            }
            db.add(WebsiteClassification(website_id=wid, scan_id=scan.id, method="rules", is_current=True, **rec))
            if home.get("org_names") and not w.organization_id:
                org = Organization(name=home["org_names"][0], domain=w.registrable_domain, source="schema.org",
                                   evidence={"page": home.get("url")})
                db.add(org)
                db.flush()
                w.organization_id = org.id
            w.language = (home.get("html_lang") or "")[:16] or w.language
            w.country_signals = feat.country_signals(feats, w.host) or w.country_signals

        # Advance publishers, mixed sites with editorial operations, and popular UNKNOWNs (a rendered
        # scan may succeed where the static fetch was refused).
        go = bool(res.is_publisher) or "GENERAL_CONTENT_PUBLISHER" in res.secondary_categories \
            or (res.primary_category == "UNKNOWN" and (w.discovery_priority or 0) >= 60)
        if feats or go:
            claims.complete(db, wid, "classify", "DONE" if go else "SKIPPED",
                            {"category": res.primary_category, "confidence": res.confidence, "scan_status": status},
                            advance=go, next_priority=w.discovery_priority)
            if not go:
                claims.enqueue(db, wid, "score")  # still scored so it appears (excluded / low) with an explanation
        else:
            fail_msg = problem or "fetch failed"  # evidence kept; stage retried with backoff
        _refresh_summary(db, wid)
    if fail_msg:
        claims.fail(wid, "classify", fail_msg)


# =================================================================== SUPPLY (ads.txt)
def run_supply(ids: list[int]) -> None:
    asyncio.run(_supply_batch(ids))


async def _fetch_ads_txt(fetcher: SafeFetcher, host: str) -> tuple[FetchResult, str, adstxt.ParsedAdsTxt | None]:
    r = await fetcher.get(f"https://{host}/ads.txt", max_bytes=2_000_000)
    if r.error and not r.status:
        r = await fetcher.get(f"http://{host}/ads.txt", max_bytes=2_000_000)
    if r.blocked:
        return r, "ROBOTS_DISALLOWED" if "robots" in r.blocked else "FETCH_FAILED", None
    if r.status is None:
        return r, "FETCH_FAILED", None
    if r.status == 404 or r.status == 410:
        return r, "NOT_FOUND", None
    if r.status >= 400:
        return r, "FETCH_FAILED", None
    final_host = urlsplit(r.final_url).hostname or host
    if not same_site(final_host, host) and len(r.redirects) > 1:
        return r, "FETCH_FAILED", None  # more than one cross-domain redirect is not honoured
    text = r.text()
    if adstxt.looks_like_html(text):
        return r, "NOT_TEXT", None
    parsed = adstxt.parse(text)
    if not parsed.records and not parsed.variables:
        return r, "EMPTY", parsed
    return r, "FOUND", parsed


async def _supply_batch(ids: list[int]) -> None:
    with session_scope() as db:
        sites = [db.get(Website, i) for i in ids]
    reg = load_registry()
    sem = asyncio.Semaphore(16)

    async def one(w: Website):
        async with sem:
            host = urlsplit(w.preferred_origin).hostname or w.host
            r, status, parsed = await _fetch_ads_txt(fetcher, host)
            inherited = None
            if status == "NOT_FOUND" and w.host != w.registrable_domain:
                r2, st2, p2 = await _fetch_ads_txt(fetcher, w.registrable_domain)
                if st2 == "FOUND":
                    r, status, parsed, inherited = r2, st2, p2, w.registrable_domain
            return w, r, status, parsed, inherited

    async with SafeFetcher() as fetcher:
        outcomes = await asyncio.gather(*(one(w) for w in sites if w), return_exceptions=True)
    for item in outcomes:
        if isinstance(item, BaseException):
            log.error("ads.txt batch item failed: %s", item)
            continue
        w, r, status, parsed, inherited = item
        try:
            with session_scope() as db:
                prev = db.scalar(select(func.count()).select_from(AdsTxtFile).where(AdsTxtFile.website_id == w.id, AdsTxtFile.is_current.is_(True)))
                if status == "FETCH_FAILED" and prev:
                    # keep previous evidence current; record the failed attempt as non-current
                    db.add(AdsTxtFile(website_id=w.id, url=r.url, final_url=r.final_url, http_status=r.status, status=status, is_current=False,
                                      variables={"error": r.error or r.blocked}))
                else:
                    db.execute(update(AdsTxtFile).where(AdsTxtFile.website_id == w.id).values(is_current=False))
                    db.execute(update(AdsTxtRecord).where(AdsTxtRecord.website_id == w.id).values(is_current=False))
                    f = AdsTxtFile(website_id=w.id, url=r.url, final_url=r.final_url, http_status=r.status, status=status,
                                   sha256=hashlib.sha256(r.body).hexdigest() if r.body else None,
                                   record_count=len(parsed.records) if parsed else 0,
                                   malformed_count=len(parsed.malformed) if parsed else 0,
                                   variables={**(parsed.variables if parsed else {}), **({"_inherited_from": inherited} if inherited else {}),
                                              **({"_error": r.error or r.blocked} if status == "FETCH_FAILED" else {})},
                                   malformed_sample=(parsed.malformed[:25] if parsed else None),
                                   raw_text=(r.text()[:500_000] if status == "FOUND" else None), is_current=True)
                    db.add(f)
                    db.flush()
                    if parsed and parsed.records:
                        db.execute(AdsTxtRecord.__table__.insert(), [
                            {"file_id": f.id, "website_id": w.id, "ad_system_domain": rec.ad_system_domain,
                             "seller_account_id": rec.seller_account_id, "relationship": rec.relationship,
                             "cert_authority_id": rec.cert_authority_id, "vendor_key": reg.vendor_for_ad_system(rec.ad_system_domain),
                             "line_no": rec.line_no, "is_current": True} for rec in parsed.records])
                claims.complete(db, w.id, "supply", "DONE", {"ads_txt": status}, next_priority=w.discovery_priority)
                _refresh_summary(db, w.id)
        except Exception as exc:  # noqa: BLE001
            log.exception("persist ads.txt failed for %s", w.host)
            claims.fail(w.id, "supply", f"{type(exc).__name__}: {exc}")


# =================================================================== ADTECH (rendered + static + ads.txt)
def run_adtech(ids: list[int]) -> None:
    asyncio.run(_adtech_batch(ids))


def _static_pages(db: Session, wid: int) -> list[PageObservation]:
    scan = db.scalar(select(Scan).where(Scan.website_id == wid, Scan.kind == "http_fetch").order_by(Scan.id.desc()).limit(1))
    if scan is not None and scan.status != "OK":
        ok_scan = db.scalar(select(Scan).where(Scan.website_id == wid, Scan.kind == "http_fetch", Scan.status == "OK")
                            .order_by(Scan.id.desc()).limit(1))
        scan = ok_scan or scan
    out = []
    if scan:
        for p in scan.pages:
            html = _ungz(p.html_gz)
            out.append(PageObservation(url=p.final_url or p.url, role=p.page_role, ok=bool(html), rendered=False, html=html,
                                       script_urls=p.script_urls or [], blocked_reason=p.blocked_reason))
    return out


def _ads_obs(db: Session, wid: int) -> tuple[AdsTxtObservation | None, AdsTxtFile | None]:
    f = db.scalar(select(AdsTxtFile).where(AdsTxtFile.website_id == wid, AdsTxtFile.is_current.is_(True)).order_by(AdsTxtFile.id.desc()).limit(1))
    if not f:
        return None, None
    recs = db.execute(select(AdsTxtRecord.ad_system_domain, AdsTxtRecord.seller_account_id, AdsTxtRecord.relationship)
                      .where(AdsTxtRecord.file_id == f.id)).all()
    return AdsTxtObservation(f.status, [{"ad_system_domain": a, "seller_account_id": b, "relationship": c} for a, b, c in recs]), f


async def _adtech_batch(ids: list[int]) -> None:
    s = get_settings()
    with session_scope() as db:
        jobs = []
        for wid in ids:
            w = db.get(Website, wid)
            if not w:
                continue
            cls = db.scalar(select(WebsiteClassification).where(WebsiteClassification.website_id == wid,
                                                                WebsiteClassification.is_current.is_(True)).limit(1))
            articles = []
            if cls and cls.features:
                articles = [p["url"] for p in cls.features.get("pages", [])[1:] if p.get("url")]
            urls = [w.preferred_origin.rstrip("/") + "/"] + articles[: max(0, s.adtech_max_pages - 1)]
            jobs.append((wid, w.host, urls))

    rendered: dict[int, list[Any]] = {wid: [] for wid, _, _ in jobs}
    render_error: dict[int, str] = {}
    if s.playwright_enabled and jobs:
        from app.adtech.render import Renderer

        try:
            async with Renderer() as renderer:
                async def site(wid: int, host: str, urls: list[str]):
                    for u in urls:  # sequential per site = polite
                        rendered[wid].append(await renderer.render(u))
                await asyncio.gather(*(site(*j) for j in jobs))
        except Exception as exc:  # browser could not start: all sites fall back to static evidence
            log.exception("renderer failed")
            for wid, _, _ in jobs:
                render_error[wid] = f"renderer unavailable: {type(exc).__name__}: {exc}"

    for wid, host, _urls in jobs:
        try:
            _persist_adtech(wid, rendered.get(wid, []), render_error.get(wid))
        except Exception as exc:  # noqa: BLE001
            log.exception("persist adtech failed for %s", host)
            claims.fail(wid, "adtech", f"{type(exc).__name__}: {exc}")


def _inventory_profile(renders: list[Any]) -> dict[str, Any] | None:
    ok = [r for r in renders if r.ok]
    if not ok:
        return None
    types: dict[str, int] = {}
    sizes: set[str] = set()
    per_page = []
    with_creative = 0
    for r in ok:
        pl = r.page.get("placements") or []
        per_page.append(len(pl))
        for p in pl:
            types[p["type"]] = types.get(p["type"], 0) + 1
            if p.get("has_iframe"):
                with_creative += 1
        for sl in ((r.page.get("gpt") or {}).get("slots") or []):
            sizes.update(sl.get("sizes") or [])
        for inst in r.page.get("prebid") or []:
            sizes.update(inst.get("ad_unit_sizes") or [])
    return {
        "pages_sampled": len(ok),
        "placements_per_page": round(sum(per_page) / len(per_page), 1),
        "types": types,
        "advertised_sizes": sorted(sizes)[:40],
        "containers_with_creative_iframe": with_creative,
        "video": any((r.page.get("video") or {}).get("ima") or any(n.get("url", "").find("imasdk") >= 0 for n in r.network[:2000]) for r in ok),
        "note": "Sampled pages only; counts are placements observed in the DOM, not impressions or fill.",
    }


def _persist_adtech(wid: int, renders: list[Any], render_error: str | None) -> None:
    s = get_settings()
    with session_scope() as db:
        w = db.get(Website, wid)
        pages = _static_pages(db, wid)
        page_rows = []
        for r in renders:
            obs = PageObservation(url=r.final_url or r.url, role="homepage" if not page_rows else "article", ok=r.ok, rendered=True,
                                  html=r.html if r.ok else "", script_urls=r.script_urls,
                                  network_urls=[n["url"] for n in r.network if not n.get("blocked")],
                                  globals_present=(r.page.get("globals") or {}), prebid=r.page.get("prebid") or [],
                                  gpt=r.page.get("gpt"), blocked_reason=r.blocked_reason or r.error)
            pages.append(obs)
            page_rows.append({
                "url": r.url, "final_url": r.final_url, "page_role": obs.role, "http_status": r.status, "content_type": "text/html",
                "html_sha256": hashlib.sha256(r.html.encode()).hexdigest() if r.html else None, "html_gz": _gz(r.html) if r.html else None,
                "script_urls": r.script_urls[:300], "network_requests": r.network[:1500],
                "page_globals": {k: r.page.get(k) for k in ("globals", "prebid", "gpt", "placements", "video", "title")},
                "blocked_reason": r.blocked_reason or r.error,
            })
        if page_rows or render_error:
            n_ok = sum(1 for r in renders if r.ok)
            status = "OK" if n_ok == len(renders) and renders else ("PARTIAL" if n_ok else ("FAILED" if render_error or renders else "SKIPPED"))
            browser = renders[0].browser_version if renders else None
            scan = _store_scan(db, wid, "rendered", f"playwright-chromium-{browser or 'n/a'}", status, render_error, page_rows,
                               meta={"settle_ms": s.playwright_settle_ms})
        else:
            scan = None
        ads, ads_file = _ads_obs(db, wid)
        results = detector.detect(pages, ads)

        n_rendered_ok = sum(1 for r in renders if r.ok)
        prev = db.scalar(select(func.count()).select_from(DetectedTechnology).where(
            DetectedTechnology.website_id == wid, DetectedTechnology.is_current.is_(True)))
        render_attempted = bool(renders) or bool(render_error)
        # A failed render must not replace conclusions that earlier rendered evidence supported.
        usable = n_rendered_ok > 0 or (not render_attempted and any(p.ok for p in pages)) or not prev
        if usable:
            db.execute(update(DetectedTechnology).where(DetectedTechnology.website_id == wid,
                                                        DetectedTechnology.is_current.is_(True)).values(is_current=False))
            for vr in results:
                d = DetectedTechnology(website_id=wid, vendor_key=vr.vendor_key, vendor_name=vr.vendor_name, category=vr.category,
                                       status=vr.status, confidence=vr.confidence, detail=vr.detail,
                                       engine_version=detector.ENGINE_VERSION, is_current=True)
                for e in vr.evidence:
                    d.evidence.append(TechnologyEvidence(kind=e.kind, value=e.value[:2000], page_url=e.page_url,
                                                         scan_id=scan.id if scan else None, observation=e.observation))
                db.add(d)
            inv = _inventory_profile(renders)
            if inv:
                db.execute(update(AdInventory).where(AdInventory.website_id == wid).values(is_current=False))
                db.add(AdInventory(website_id=wid, scan_id=scan.id if scan else None, pages_sampled=inv["pages_sampled"], profile=inv))

        # rescue: static fetch failed/UNKNOWN but rendering worked -> classify from rendered HTML
        cls = db.scalar(select(WebsiteClassification).where(WebsiteClassification.website_id == wid,
                                                            WebsiteClassification.is_current.is_(True)).limit(1))
        ok_renders = [r for r in renders if r.ok and r.html]
        if (cls is None or cls.primary_category == "UNKNOWN") and ok_renders:
            fs = [feat.extract_safe(r.html, r.final_url or r.url) for r in ok_renders]
            res = rules.classify(w.host, fs)
            if res.primary_category != "UNKNOWN":
                db.execute(update(WebsiteClassification).where(WebsiteClassification.website_id == wid).values(is_current=False))
                rec = rules.as_record(res)
                rec["features"] = {"scores": res.scores, "home": {k: fs[0].get(k) for k in ("title", "business_links", "org_names", "html_lang")},
                                   "pages": [{"url": f.get("url"), "word_count": f.get("word_count")} for f in fs], "source": "rendered"}
                db.add(WebsiteClassification(website_id=wid, scan_id=scan.id if scan else None, method="rules-rendered", is_current=True, **rec))

        claims.complete(db, wid, "adtech", "DONE",
                        {"rendered_ok": n_rendered_ok, "rendered_total": len(renders), "render_error": render_error,
                         "ads_txt": ads_file.status if ads_file else None}, next_priority=w.discovery_priority)
        w.last_analyzed_at = _now()
        _refresh_summary(db, wid)


# =================================================================== SCORE
def run_score(ids: list[int]) -> None:
    for wid in ids:
        try:
            run_score_for(wid, complete_stage=True)
        except Exception as exc:  # noqa: BLE001
            log.exception("score failed for %s", wid)
            claims.fail(wid, "score", f"{type(exc).__name__}: {exc}")


def build_bundle(db: Session, wid: int) -> tuple[opp.EvidenceBundle, WebsiteClassification | None, AdsTxtFile | None]:
    cls = db.scalar(select(WebsiteClassification).where(WebsiteClassification.website_id == wid,
                                                        WebsiteClassification.is_current.is_(True)).order_by(WebsiteClassification.id.desc()).limit(1))
    dets = db.scalars(select(DetectedTechnology).where(DetectedTechnology.website_id == wid, DetectedTechnology.is_current.is_(True))).all()
    vendors = {d.vendor_key: {"status": d.status, "confidence": d.confidence, "category": d.category, "name": d.vendor_name,
                              "detail": d.detail or {}} for d in dets}
    # evidence comes from the most recent *successful* scans (a later failed scan does not erase it)
    rscan = db.scalar(select(Scan).where(Scan.website_id == wid, Scan.kind == "rendered", Scan.status.in_(("OK", "PARTIAL")))
                      .order_by(Scan.id.desc()).limit(1))
    sscan = db.scalar(select(Scan).where(Scan.website_id == wid, Scan.kind == "http_fetch", Scan.status == "OK")
                      .order_by(Scan.id.desc()).limit(1))
    r_ok = sum(1 for p in (rscan.pages if rscan else []) if not p.blocked_reason and p.html_gz)
    s_ok = sum(1 for p in (sscan.pages if sscan else []) if p.html_gz)
    ads_file = db.scalar(select(AdsTxtFile).where(AdsTxtFile.website_id == wid, AdsTxtFile.is_current.is_(True)).order_by(AdsTxtFile.id.desc()).limit(1))
    systems = []
    if ads_file:
        systems = sorted(set(db.scalars(select(AdsTxtRecord.ad_system_domain).where(AdsTxtRecord.file_id == ads_file.id))))
    inv = db.scalar(select(AdInventory).where(AdInventory.website_id == wid, AdInventory.is_current.is_(True)).order_by(AdInventory.id.desc()).limit(1))
    words = [p.get("word_count") or 0 for p in ((cls.features or {}).get("pages", [])[1:] if cls else [])]
    bundle = opp.EvidenceBundle(
        is_publisher=cls.is_publisher if cls else None, category=cls.primary_category if cls else None,
        classification_confidence=cls.confidence if cls else 0.0, vendors=vendors, rendered_pages_ok=r_ok, static_pages_ok=s_ok,
        adtech_scanned=bool(dets), ads_txt_status=ads_file.status if ads_file else None,
        ads_txt_record_count=ads_file.record_count if ads_file else 0, ads_txt_systems=systems,
        inventory=inv.profile if inv else {}, article_word_counts=words,
    )
    return bundle, cls, ads_file


def run_score_for(wid: int, complete_stage: bool = False) -> None:
    weights = get_setting("scoring_weights")
    with session_scope() as db:
        w = db.get(Website, wid)
        bundle, cls, ads_file = build_bundle(db, wid)
        crux, tranco = _popularity(db, wid)
        bundle.popularity_points, _ = scoring.popularity_score(crux, tranco, weights)
        opps = opp.assess(bundle) if (cls and cls.is_publisher is not False) else []
        org = db.get(Organization, w.organization_id).name if w.organization_id else None
        home = ((cls.features or {}).get("home") or {}) if cls else {}
        seller_match = False
        if ads_file:
            direct = db.execute(select(AdsTxtRecord.ad_system_domain, AdsTxtRecord.seller_account_id).where(
                AdsTxtRecord.file_id == ads_file.id, AdsTxtRecord.relationship == "DIRECT")).all()
            if direct:
                hit = db.scalar(select(SellerEntity.id).where(
                    SellerEntity.domain == w.registrable_domain,
                    SellerEntity.seller_id.in_([d[1] for d in direct][:200])).limit(1))
                seller_match = bool(hit)
        rscan_at = db.scalar(select(func.max(Scan.finished_at)).where(Scan.website_id == wid))
        inp = scoring.ScoreInput(
            excluded=w.excluded, exclusion_reason=w.exclusion_reason, category=cls.primary_category if cls else None,
            secondary=(cls.secondary_categories or []) if cls else [], is_publisher=cls.is_publisher if cls else None,
            classification_confidence=cls.confidence if cls else 0.0, crux_buckets=crux, tranco_best=tranco, bundle=bundle,
            opportunities=opps, organization=org, ads_txt_contact=bool(ads_file and (ads_file.variables or {}).get("CONTACT")),
            ads_txt_owner_or_manager=bool(ads_file and ((ads_file.variables or {}).get("OWNERDOMAIN") or (ads_file.variables or {}).get("MANAGERDOMAIN"))),
            seller_name_match=seller_match, business_links=home.get("business_links") or {}, last_scan_at=rscan_at,
        )
        res = scoring.compute(inp, weights)

        db.execute(update(OpportunityAssessment).where(OpportunityAssessment.website_id == wid,
                                                       OpportunityAssessment.is_current.is_(True)).values(is_current=False))
        for o in opps:
            db.add(OpportunityAssessment(website_id=wid, opportunity_type=o.type, label=o.label, confidence=o.confidence, evidence=o.evidence,
                                         hypothesis=o.hypothesis, missing_information=o.missing, verification_step=o.verification,
                                         suggested_approach=o.approach, engine_version=opp.ENGINE_VERSION))
        override = db.scalar(select(ManualOverride).where(ManualOverride.website_id == wid, ManualOverride.field == "queue",
                                                          ManualOverride.active.is_(True)).order_by(ManualOverride.id.desc()).limit(1))
        db.execute(update(Score).where(Score.website_id == wid, Score.is_current.is_(True)).values(is_current=False))
        db.add(Score(website_id=wid, popularity=res.popularity, ad_opportunity=res.ad_opportunity, audience_geo=res.audience_geo,
                     inventory=res.inventory, actionability=res.actionability, evidence_quality=res.evidence_quality, total=res.total,
                     computed_queue=res.queue, queue=override.value if override else res.queue, evidence_confidence=res.evidence_confidence,
                     explanation=res.explanation, missing_critical=res.missing_critical, next_action=res.next_action, weights=weights,
                     engine_version=scoring.ENGINE_VERSION))
        if complete_stage:
            claims.complete(db, wid, "score", "DONE", {"total": res.total, "queue": res.queue})
        _refresh_summary(db, wid)


# =================================================================== summary
def _refresh_summary(db: Session, wid: int) -> None:
    from app.services.summary import refresh_summary

    db.flush()
    refresh_summary(db, wid)


STAGE_RUNNERS = {"qualify": run_qualify, "classify": run_classify, "supply": run_supply, "adtech": run_adtech, "score": run_score}
