# Purify Publisher Intelligence — project summary

A clean, self-contained overview of the tool: what it is, what it does, how it was
built and verified, and where it stands. For deeper detail see
[ARCHITECTURE.md](ARCHITECTURE.md), [VERIFICATION.md](VERIFICATION.md) and
[VPS_CHECKLIST.md](VPS_CHECKLIST.md).

## What it is

A self-hostable web application that **finds websites Purify Digital could sell programmatic
advertising services to**. It discovers sites, works out which are advertising-supported
publishers, inspects each one's advertising technology, and ranks them into monetization
opportunities — with the evidence behind every decision.

It was built in phases 1–4 of the original brief, **without traffic estimates** (traffic is
researched manually; see "Deliberate scope choices").

## What it does, step by step

1. **Discovers websites** from public popularity datasets (Google CrUX top lists, Tranco
   ranking), from `sellers.json` relationships, and from CSV/XLSX uploads of existing lists.
   A discovery job can target a popularity range (e.g. "Bulgaria, ranks 10K–100K, up to 2,000
   sites").
2. **Filters out the junk** cheaply, before any heavy work: government sites, adult/piracy
   domains, large platforms and infrastructure subdomains.
3. **Classifies each site** by fetching a few pages: news, sports, gaming, tech, finance,
   entertainment, lifestyle, education, forum, tool — or *not a publisher* (shop, SaaS,
   corporate, bank, marketplace, government). The niche is decided primarily from what the
   site's **headlines** are about. A site with no advertising evidence but clear business
   signals is classified as that business, not a publisher.
4. **Reads `ads.txt`** (IAB standard parser) and stores the declared seller relationships.
5. **Scans the advertising stack in a real headless browser** (Playwright + Chromium):
   Google Ad Manager, AdSense, Prebid.js (with configured/requested/responding bidders),
   Amazon Publisher Services, and 70+ SSPs and managed partners. In the EU it **accepts cookie
   consent banners** in its own throwaway browser so the ad stack a real visitor sees can load
   (`CONSENT_MODE=accept`; recorded in the evidence).
6. **Assesses the opportunity** (types A–G, e.g. "GAM without observed header bidding",
   "AdSense-focused", "limited bidder competition"), with evidence, confidence, what's missing
   and how to verify it.
7. **Scores and ranks** each site 0–100 into queues. The queue that matters for prospecting is
   `HIGH_POTENTIAL_VERIFY_TRAFFIC` — the shortlist to research traffic on by hand.

All of this runs continuously and on a schedule; a **live Processing panel** on the dashboard
shows per-step progress, speed and time left, and what's being processed right now.

## Honesty guarantees (built in)

- **No invented traffic.** "Popular" means a CrUX band or Tranco rank, labelled as such
  everywhere — never presented as visit counts.
- **Uncertainty is visible.** Ad-tech findings carry one of five statuses:
  `DETECTED_ACTIVE_SIGNALS` (runtime evidence, *not* proof of auctions/fill/revenue/contracts),
  `POSSIBLE`, `DECLARED_AUTHORIZATION_ONLY` (ads.txt only), `NOT_OBSERVED`, `SCAN_INCONCLUSIVE`.
- **Blocked ≠ empty.** A site that blocks the scanner (paywall, 403, anti-bot challenge,
  robots.txt disallow) is reported as inconclusive, never as "no advertising".
- **Raw observations are stored separately from conclusions**, so classifications, scores and
  opportunities can be recomputed without re-crawling.

## Architecture (one line each)

- **Backend:** FastAPI + SQLAlchemy/Alembic on PostgreSQL; JWT roles, audit log, CSV/XLSX export.
- **Workers:** Celery on Redis — four pools (jobs, fast DB stages, HTTP fetch, browser render) —
  with a dispatcher, resumable checkpointed jobs, stage leases and a crash watchdog.
- **Rendering:** Playwright + Chromium, behind an SSRF guard and robots.txt (RFC 9309).
- **Frontend:** Next.js + Tailwind — dashboard, publisher explorer, website profile, discovery,
  import, opportunity pipeline, settings.
- **Deploy:** one `docker compose up` (Postgres, Redis, API, workers, beat, frontend).

## How it's run

- **Local (laptop/desktop):** Docker Desktop → `docker compose up -d --build` → the UI at
  `http://localhost:3000`. Good for testing and small markets.
- **Production:** a VPS (≥4 vCPU, 8 GB RAM). See [VPS_CHECKLIST.md](VPS_CHECKLIST.md).

## Verification

- **117 automated tests** (classification, ad-tech detection, ads.txt/sellers.json parsing,
  SSRF, robots.txt, scoring, API, resumable jobs, and a full end-to-end pipeline on local
  fixtures).
- **Validated against real websites** with `backend/scripts/live_validate.py` and a 116-site
  hand-labelled benchmark. Latest run: publisher-vs-non-publisher **93%** correct on sites the
  scanner could read; niche **73%**; Google Ad Manager seen active on 61 sites, Prebid on 49.
- Several bugs were found only by real-website runs (and fixed): a classifier crash on BBC's
  schema markup, cookie-wall false negatives, over-strict robots handling, over-broad "news"
  labelling. [VERIFICATION.md](VERIFICATION.md) has the detail.

## Deliberate scope choices

- **Traffic estimates: out.** The platform ranks by popularity for manual traffic research;
  `VERIFIED_HIGH_VALUE` is reachable only by a manual override (with a reason, audited).
- **Metrica: not integrated.** Its Terms of Service forbid automated/API access and storing its
  data.
- **Not built (phases 5–6 and optional pieces):** contact discovery, scheduled rechecks and
  change alerts, HTTP Archive/BigQuery reverse lookup, optional LLM classification.

## Known limitations

- ~25–30% of big sites block automated access (paywalls, 403s, anti-bot, robots.txt) and are
  reported as `UNKNOWN`/inconclusive — by design, not bypassed.
- Niche labelling is weakest on non-English sites (topic vocabularies are mostly English); a few
  non-publishers still slip through. These do not affect the publisher-vs-non-publisher split,
  which is what prospecting depends on.
- The browser scan is the slowest step: roughly 150–300 sites/hour on a laptop.

## Where it lives

GitHub: `dimitarpdwork-tech/Purify` (branch `main`).
