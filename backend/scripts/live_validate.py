"""LIVE validation against real websites. Run on the deployment host (needs open internet):

    docker compose exec api python -m scripts.live_validate                 # infra checks + full benchmark
    docker compose exec api python -m scripts.live_validate --limit 20      # quick run
    docker compose exec api python -m scripts.live_validate --no-render     # skip Playwright

It uses the same code paths as the pipeline (SafeFetcher -> features/classifier -> ads.txt parser ->
Playwright renderer -> ad-tech detector) but evaluates in memory: it does NOT write to the database.

Output: /data/validation/<timestamp>/{summary.md, results.json, sites/<host>.json}
Exit code 1 if an infrastructure check fails (network, robots, SSRF guard, browser). Classification
accuracy is reported for human review, not used as a pass/fail gate.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.adtech import detector
from app.adtech.detector import AdsTxtObservation, PageObservation
from app.classify import features as feat
from app.classify import rules
from app.core.config import get_settings
from app.discovery import datasets
from app.models import Website
from app.pipeline.stages import _fetch_ads_txt, _fetch_site_pages
from app.services.normalize import normalize
from app.services.safe_fetch import SafeFetcher

BENCH = Path(__file__).resolve().parent.parent / "benchmark" / "benchmark_sites.csv"


def _ws(host: str) -> Website:
    n = normalize(host)
    return Website(host=n.host, registrable_domain=n.registrable_domain, preferred_origin=n.origin, discovery_priority=50)


async def infra_checks() -> list[dict]:
    out = []

    def rec(name, ok, detail):
        out.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    async with SafeFetcher() as f:
        r = await f.get("https://example.com/")
        rec("outbound HTTPS fetch", r.ok, f"status={r.status} error={r.error or r.blocked}")
        r = await f.get("https://www.google.com/search?q=test")
        rec("robots.txt respected (google.com/search is disallowed)", bool(r.blocked and "robots" in r.blocked), r.blocked or f"status={r.status}")
        for u in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8000/api/health", "http://localhost/"):
            r = await f.get(u)
            rec(f"SSRF guard blocks {u}", bool(r.blocked) and not r.ok, r.blocked or f"status={r.status}")
    try:
        p = datasets.crux_latest_period()
        rec("CrUX top-list reachable", True, f"latest global period {p}")
    except Exception as exc:  # noqa: BLE001
        rec("CrUX top-list reachable", False, str(exc))
    lid = datasets.tranco_list_id()
    rec("Tranco list reachable", bool(lid), f"list id {lid}")
    try:
        _sys, url = get_settings().split_sellers_source(get_settings().sellers_json_source_list[0])
        r = httpx.head(url, timeout=20, follow_redirects=True)
        rec(f"sellers.json reachable ({url})", r.status_code == 200, f"status={r.status_code} size={r.headers.get('content-length')}")
    except httpx.HTTPError as exc:
        rec("sellers.json reachable", False, str(exc))
    return out


async def evaluate_site(row: dict, fetcher: SafeFetcher, renderer, sem: asyncio.Semaphore) -> dict:
    """Never raises: a failure on one site is recorded in its result and the run continues."""
    try:
        return await _evaluate_site(row, fetcher, renderer, sem)
    except Exception as exc:  # noqa: BLE001
        import traceback

        print(f"  {row['host']:32s} ERROR {type(exc).__name__}: {exc}")
        return {"host": row["host"], "expected": row["expected_category"], "expected_is_publisher": row["expected_is_publisher"] == "true",
                "group": row["group"], "notes": row["notes"], "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2000:], "static": {"pages_ok": 0, "problem": f"script error: {exc}"},
                "classification": {"category": "ERROR", "is_publisher": None, "confidence": 0}, "ads_txt": {"status": "ERROR"},
                "adtech": {}, "summary": {"gam": None, "prebid": None}}


async def _evaluate_site(row: dict, fetcher: SafeFetcher, renderer, sem: asyncio.Semaphore) -> dict:
    s = get_settings()
    host = row["host"]
    res: dict = {"host": host, "expected": row["expected_category"], "expected_is_publisher": row["expected_is_publisher"] == "true",
                 "group": row["group"], "notes": row["notes"]}
    async with sem:
        t0 = time.monotonic()
        w = _ws(host)
        results, feats, problem = await _fetch_site_pages(fetcher, w, s.classification_max_pages)
        res["static"] = {"pages_ok": len(feats), "problem": problem,
                         "attempts": [{"url": r.url, "final": r.final_url, "status": r.status, "error": r.error, "blocked": r.blocked} for r in results]}
        cls = rules.classify(w.host, feats, fetch_ok=bool(feats), blocked_reason=problem)
        res["classification"] = {"category": cls.primary_category, "is_publisher": cls.is_publisher, "confidence": cls.confidence,
                                 "secondary": cls.secondary_categories, "top_signals": [e["signal"] for e in cls.supporting[:6]],
                                 "contradictory": [e.get("signal") for e in cls.contradictory[:4]]}
        ar, astatus, parsed = await _fetch_ads_txt(fetcher, urlsplit(w.preferred_origin).hostname or w.host)
        res["ads_txt"] = {"status": astatus, "records": len(parsed.records) if parsed else 0, "malformed": len(parsed.malformed) if parsed else 0,
                          "variables": {k: v[:3] for k, v in (parsed.variables.items() if parsed else [])}}
        ads_obs = AdsTxtObservation(astatus, [{"ad_system_domain": r.ad_system_domain, "seller_account_id": r.seller_account_id,
                                               "relationship": r.relationship} for r in (parsed.records if parsed else [])])
        static_obs = []
        for r in results:
            if r.ok and "html" in (r.content_type or ""):
                static_obs.append(PageObservation(url=r.final_url, ok=True, html=r.text()))
        pages = static_obs
        res["render"] = None
        if renderer is not None:
            base = (feats[0]["url"] if feats else f"https://{host}/")
            urls = [base] + [f["url"] for f in feats[1:2]]
            rr = []
            for u in urls:
                x = await renderer.render(u)
                rr.append(x)
                pages.append(PageObservation(url=x.final_url or u, ok=x.ok, rendered=True, html=x.html if x.ok else "",
                                             script_urls=x.script_urls, network_urls=[n["url"] for n in x.network if not n.get("blocked")],
                                             globals_present=x.page.get("globals") or {}, prebid=x.page.get("prebid") or [],
                                             gpt=x.page.get("gpt"), consent=x.page.get("consent"), blocked_reason=x.blocked_reason or x.error))
            res["render"] = [{"url": x.url, "ok": x.ok, "status": x.status, "blocked": x.blocked_reason, "error": x.error,
                              "requests": len(x.network), "elapsed_ms": x.elapsed_ms,
                              "placements": len(x.page.get("placements") or []),
                              "prebid": [{"global": p.get("global"), "version": p.get("version"), "bidders": p.get("configured_bidders"),
                                          "requested": p.get("requested_bidders")} for p in (x.page.get("prebid") or [])],
                              "gpt_slots": len(((x.page.get("gpt") or {}).get("slots")) or []),
                              "consent": x.page.get("consent"), "consent_action": x.page.get("consent_action")} for x in rr]
            if cls.primary_category == "UNKNOWN" and any(x.ok and x.html for x in rr):
                fs = [feat.extract_safe(x.html, x.final_url or x.url) for x in rr if x.ok and x.html]
                c2 = rules.classify(w.host, fs)
                res["classification_rendered_rescue"] = {"category": c2.primary_category, "confidence": c2.confidence}
        dets = detector.detect(pages, ads_obs)
        res["adtech"] = {d.vendor_key: {"status": d.status, "confidence": d.confidence,
                                        "evidence": [e.kind + ": " + e.value[:120] for e in d.evidence[:4]],
                                        **({"why": d.detail.get("reasons")} if d.detail.get("reasons") else {})}
                         for d in dets if d.category not in ("cms", "analytics", "forum_software", "ecommerce_platform")}
        res["summary"] = detector.summarize(dets)
        res["elapsed_s"] = round(time.monotonic() - t0, 1)
    print(f"  {host:32s} {res['classification']['category']:26s} exp={row['expected_category']:26s} ads.txt={astatus:10s} "
          f"gam={res['summary']['gam']} prebid={res['summary']['prebid']}")
    return res


def accept(row: dict, got: str, rescue: str | None) -> bool:
    exp = row["expected"]
    cats = {got, rescue} - {None}
    if exp in cats:
        return True
    alt = row.get("notes", "")
    return any(c and c.split("_")[0] in alt.upper() for c in cats)  # "NEWS also acceptable" style notes


def write_report(outdir: Path, infra: list[dict], results: list[dict], rendered: bool) -> None:
    (outdir / "sites").mkdir(parents=True, exist_ok=True)
    for r in results:
        (outdir / "sites" / f"{r['host']}.json").write_text(json.dumps(r, indent=1, default=str))
    (outdir / "results.json").write_text(json.dumps({"infra": infra, "sites": results}, indent=1, default=str))
    n = len(results)
    correct = [r for r in results if accept(r, r["classification"]["category"], (r.get("classification_rendered_rescue") or {}).get("category"))]
    pub_tp = sum(1 for r in results if r["classification"]["is_publisher"] and r["expected_is_publisher"])
    pub_fp = sum(1 for r in results if r["classification"]["is_publisher"] and not r["expected_is_publisher"])
    pub_fn = sum(1 for r in results if r["classification"]["is_publisher"] is False and r["expected_is_publisher"])
    unknown = sum(1 for r in results if r["classification"]["category"] == "UNKNOWN")
    errors = [r["host"] for r in results if r.get("error")]
    clicked = [r["host"] for r in results if any((x.get("consent_action") or {}).get("clicked") for x in (r.get("render") or []))]
    gated = [r["host"] for r in results if any(((r.get("adtech") or {}).get(k) or {}).get("status") == "SCAN_INCONCLUSIVE"
                                               and "consent" in json.dumps((r.get("adtech") or {}).get(k)) for k in ("google_gam",))]
    static_fail = Counter((r["static"]["problem"] or "ok")[:60] for r in results)
    ads = Counter(r["ads_txt"]["status"] for r in results)
    rend = Counter()
    for r in results:
        for x in r.get("render") or []:
            rend["ok" if x["ok"] else (x["blocked"] or (x["error"] or "error")[:50])] += 1
    status_by_vendor = defaultdict(Counter)
    for r in results:
        for k in ("google_gam", "google_adsense", "prebid", "amazon_aps"):
            status_by_vendor[k][(r["adtech"].get(k) or {}).get("status")] += 1
    lines = [f"# Live validation report - {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M UTC}", "",
             "Real websites, evaluated in memory with the production code paths. Ground-truth labels in",
             "`benchmark/benchmark_sites.csv` were curated by hand and should be reviewed.", "",
             "## Infrastructure checks", ""]
    lines += [f"- {'PASS' if c['ok'] else 'FAIL'} - {c['check']}: {c['detail']}" for c in infra]
    lines += ["", "## Classification", "",
              f"- sites evaluated: {n}",
              f"- category matches expectation: {len(correct)}/{n} ({100 * len(correct) / max(n, 1):.0f}%)",
              f"- publisher precision: {pub_tp}/{pub_tp + pub_fp} ; publisher misses (classified non-publisher): {pub_fn}",
              f"- UNKNOWN (no usable content - blocked/challenge/failed): {unknown}",
              f"- script errors (bugs - please report): {len(errors)} {errors}",
              f"- ad-tech inconclusive because of cookie-consent walls: {len(gated)} {gated}",
              f"- cookie banner accepted by the robot: {len(clicked)} {clicked}", "",
              "| host | expected | got | conf | rescue (rendered) | static problem |", "|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda r: r["host"]):
        ok = r in correct
        lines.append(f"| {'' if ok else '**'}{r['host']}{'' if ok else '**'} | {r['expected']} | {r['classification']['category']} | "
                     f"{r['classification']['confidence']} | {(r.get('classification_rendered_rescue') or {}).get('category', '')} | "
                     f"{(r['static']['problem'] or '')[:50]} |")
    lines += ["", "## Fetch / scan outcomes", "", "Static fetch: " + ", ".join(f"{k}: {v}" for k, v in static_fail.most_common()),
              "", "ads.txt: " + ", ".join(f"{k}: {v}" for k, v in ads.most_common())]
    if rendered:
        lines += ["", "Rendered pages: " + ", ".join(f"{k}: {v}" for k, v in rend.most_common())]
    lines += ["", "## Key ad-tech statuses (count of sites)", ""]
    for k, c in status_by_vendor.items():
        lines.append(f"- {k}: " + ", ".join(f"{s}: {v}" for s, v in c.most_common()))
    lines += ["", "Review per-site evidence in `sites/<host>.json` before trusting any detection."]
    (outdir / "summary.md").write_text("\n".join(lines))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--hosts", help="comma separated subset of benchmark hosts")
    args = ap.parse_args()

    s = get_settings()
    if s.allow_private_network_fetch:
        print("Refusing to run: ALLOW_PRIVATE_NETWORK_FETCH must be false for live validation.")
        return 2
    outdir = Path(s.data_dir) / "validation" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"== infrastructure checks (report: {outdir})")
    infra = await infra_checks()

    rows = list(csv.DictReader(open(BENCH)))
    if args.hosts:
        want = {h.strip() for h in args.hosts.split(",")}
        rows = [r for r in rows if r["host"] in want]
    if args.limit:
        rows = rows[: args.limit]
    print(f"== benchmark: {len(rows)} sites")
    renderer = None
    results: list[dict] = []
    sem = asyncio.Semaphore(args.concurrency)
    async with SafeFetcher() as fetcher:
        if not args.no_render and s.playwright_enabled:
            from app.adtech.render import Renderer

            try:
                renderer_cm = Renderer()
                renderer = await renderer_cm.__aenter__()
                infra.append({"check": "headless Chromium launches", "ok": True, "detail": renderer._browser.version})
                print(f"[PASS] headless Chromium launches: {renderer._browser.version}")
            except Exception as exc:  # noqa: BLE001
                renderer = None
                infra.append({"check": "headless Chromium launches", "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
                print(f"[FAIL] headless Chromium launches: {exc}")
            if renderer is not None:
                try:
                    results = await asyncio.gather(*(evaluate_site(r, fetcher, renderer, sem) for r in rows))
                finally:
                    await renderer_cm.__aexit__(None, None, None)
        if not results:
            results = await asyncio.gather(*(evaluate_site(r, fetcher, None, sem) for r in rows))
    write_report(outdir, infra, list(results), rendered=renderer is not None)
    print(f"\nreport written to {outdir / 'summary.md'}")
    return 0 if all(c["ok"] for c in infra) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
