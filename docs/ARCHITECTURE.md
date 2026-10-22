# Architecture

## Overview

A modular monolith:

- **API:** FastAPI + SQLAlchemy 2 + Alembic on PostgreSQL 16.
- **Workers:** Celery on Redis, in four worker pools.
- **Rendering:** Playwright + Chromium.
- **Frontend:** Next.js (App Router) + Tailwind.

```
discovery jobs ─┐                 ┌─ qualify  (DB only, set-based)         queue: fast
  CrUX / Tranco │  register()     ├─ classify (static HTTP, ≤3 pages)      queue: fetch
  sellers.json  ├─► websites  ─►  ├─ supply   (ads.txt)                    queue: fetch
  CSV/XLSX      │  + provenance   ├─ adtech   (Playwright render + detect) queue: render
  manual        ┘  + popularity   └─ score    (opportunities + score)      queue: fast
```

### Pipeline stages

- **Independent status:** each stage has its own status in `stage_status`, as one of PENDING, RUNNING, DONE, SKIPPED or FAILED.
- **Dispatch:** the `dispatch` beat task claims work every 20 s with `FOR UPDATE SKIP LOCKED` and a lease, in priority order. Priority comes from popularity, and the dispatcher applies backpressure when a queue already holds work.
- **Retries:** a failed stage retries with exponential backoff, up to `STAGE_MAX_ATTEMPTS`.
- **Crash recovery:** a crashed worker's rows are reclaimed when their lease expires.

### Jobs

- **Resumability:** jobs (imports, dataset ingestion, rescoring) checkpoint every 2,000 rows.
- **Single runner:** each job holds a Postgres advisory lock, so a redelivered or watchdog-requeued copy exits immediately.
- **Watchdog:** re-queues jobs whose heartbeat is stale and whose lock is no longer held.

## Evidence model

- **Raw observations** are stored separately from conclusions:
  - `scans` and `scan_pages`: gzipped HTML, script URLs, network requests, page globals
  - `ads_txt_files` and `ads_txt_records`
  - `popularity_observations`
  - `seller_entities`
- **Conclusions** are versioned and carry `is_current`:
  - `website_classifications`
  - `detected_technologies` and `technology_evidence`
  - `ad_inventory`
  - `opportunity_assessments`
  - `scores`
- **Re-derivable:** rescoring and reclassification run from stored observations (`rescore_all`) without re-crawling.
- **Failed scans never erase conclusions:** conclusions change only when the new scan produced usable evidence, and render-derived conclusions are replaced only by a successful render.
- **`websites` holds a denormalised summary** for the explorer. It is rebuilt from the tables above and never treated as the source of truth.

### Ad-tech statuses

| Status | Meaning |
|---|---|
| `DETECTED_ACTIVE_SIGNALS` | Runtime evidence in a rendered page: a vendor ad/bid request, an initialised vendor JS object, or the vendor configured/requested as a Prebid bidder. **Not** proof of auctions, fill, revenue or a contract. |
| `POSSIBLE` | Static-only evidence: a script reference or inline pattern in un-rendered HTML. |
| `DECLARED_AUTHORIZATION_ONLY` | Present in ads.txt only. |
| `NOT_OBSERVED` | Scans succeeded and nothing was found. The confidence records the scan depth; static-only absence gets low confidence. |
| `SCAN_INCONCLUSIVE` | Scans failed or were blocked, so absence cannot be inferred. |

Opportunity B ("GAM without header bidding") requires *active* GAM evidence and a *rendered* scan
showing no Prebid, APS or OpenWrap.

## Scoring (0–100)

| Component | Points | Source |
|---|---|---|
| Popularity | 0–30 | CrUX global bucket / Tranco rank. A popularity band, not visits. Replaces the "traffic" component because traffic is out of scope. |
| Ad opportunity | 0–25 | Best opportunity hypothesis (A–G), weighted by its confidence |
| Audience / GEO | 0–15 | **Observed** presence in CrUX country lists (tiered GEOs). TLD and language are not used. |
| Inventory suitability | 0–15 | Category, plus placement formats observed in rendered pages |
| Commercial actionability | 0–10 | Organisation identified, advertise/contact page, ads.txt CONTACT, sellers.json name match |
| Evidence quality | 0–5 | Classification confidence, rendered scan, ads.txt fetched, recency |

- **Missing data** scores 0 and is listed under `missing_critical`.
- **Weights** are editable in Settings (`scoring_weights`).
- **Queues:**
  - `HIGH_POTENTIAL_VERIFY_TRAFFIC`: strong popularity + an A–E opportunity. This is the list to research manually.
  - `TECHNICAL_OPPORTUNITY`
  - `NEEDS_REVIEW`
  - `LOW_PRIORITY`
  - `EXCLUDED`
  - `VERIFIED_HIGH_VALUE`: set **only** by a manual override after traffic research. Overrides require a reason and are audited.

## Reuse decisions (licences checked 2026-10-22)

| Project | Licence | Decision |
|---|---|---|
| zakird/crux-top-lists | data repository | **Used** as a data source: global and per-country monthly CSVs fetched from raw.githubusercontent.com |
| DistriNet/tranco-list | — (generation code) | List consumed from tranco-list.eu (`top-1m.csv.zip`, `top-1m-id`). No code reused. |
| Houseofmvps/opentechalyzer | MIT (fingerprints MIT too) | **Not integrated in this build.** The in-house registry covers CMS/forum/e-commerce signals needed for classification. It can be added as an optional sidecar (`npx opentechalyzer`). |
| omkarcloud/wappalyzer-python | **GPL-3.0** | **Excluded.** It would impose GPL obligations on a proprietary codebase. No code or fingerprint data copied. |
| lsv1/AdSellers | no project licence (only CRA boilerplate licence) | Approach only. The ads.txt/sellers.json parsers were written from the IAB specs. |
| GoogleChromeLabs/ps-analysis-tool | Apache-2.0 | Not used. Independent Playwright/route-interception inspection is lighter and fits the scan model. |
| Metrica (pro.metrica.guru) | ToS forbids automated/API access and storing data | **Not integrated.** |

## Security

- **SSRF guard:** every HTTP request and every browser request (via Playwright route interception) is checked. Allowed schemes are http/https only, on default ports, with no credentials in the URL. The resolved IPs must be public, and each redirect hop is validated again.
- **Network-level egress block:** recommended on the VPS (see the checklist).
- **Crawling policy:**
  - robots.txt is respected, using our User-Agent.
  - There is a per-host minimum interval and a global concurrency cap.
  - Anti-bot challenges, CAPTCHAs, logins and paywalls are detected and reported. They are never bypassed.
- **Users and audit:** JWT auth with roles (viewer < analyst < admin). Mutations are audited, and secrets are server-side only.
