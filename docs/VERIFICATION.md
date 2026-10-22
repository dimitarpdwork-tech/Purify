# Verification status

Built and tested on 2026-10-22 in a sandbox that could reach GitHub and the package registries
only. It could **not** reach arbitrary websites, Tranco, sellers.json hosts or Docker Hub. Every
claim below states which kind of evidence backs it.

| Label | Meaning |
|---|---|
| **LIVE (real data)** | Exercised against real public data in the sandbox |
| **RUNTIME (local)** | Full runtime (Postgres + Redis + Celery workers/beat + API + Chromium) exercised end to end on local fixture sites |
| **FIXTURE** | Automated tests on synthetic inputs (`backend/tests/`) |
| **PENDING VPS** | Code complete, but never run against the real internet. Run `scripts/live_validate.py` on the VPS |

## MVP acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Import 100,000-row CSV without timeouts/data loss | **LIVE + RUNTIME** | See [100K import details](#100k-import-details) below |
| 2 | Normalize + deduplicate correctly | **LIVE + FIXTURE** | See [normalization details](#normalization-details) below |
| 3 | Resumable background classification job | **RUNTIME** | Stage leases + dispatcher verified through Celery; classification of *real* sites is **PENDING VPS** |
| 4 | Evidence-backed publisher classifications | **FIXTURE / RUNTIME**; real sites **PENDING VPS** | Classifier tests (news, gaming, recipes, forum, e-commerce, SaaS-on-WordPress, brochure-on-WordPress, parked, government, challenge page) |
| 5 | Import CrUX and Tranco | CrUX **LIVE**; Tranco **PENDING VPS** | CrUX global 202609 (100K) and BG/GB country lists (10K each) ingested from the real files. tranco-list.eu was unreachable from the sandbox |
| 6 | Rankings distinct from traffic | **By design** | Traffic is not collected in this build (your decision). Popularity is labelled "popularity, not visits" in the API, exports and UI |
| 7 | Detect key ad technologies on test pages | **RUNTIME** (real Chromium, stubbed GPT/Prebid page); real sites **PENDING VPS** | Prebid configured/requested/responding bidders, GPT slots + MCM, placements extracted by the real renderer |
| 8 | Parse ads.txt, store seller relationships | **FIXTURE / RUNTIME**; real sellers.json **PENDING VPS** | Parser tests (OWNERDOMAIN, MANAGERDOMAIN, SUBDOMAIN, malformed lines, dupes); streaming sellers.json parser tested on 6,000 entries |
| 9 | Transparent opportunity scores | **FIXTURE / RUNTIME** | `test_scoring.py`; every score stores component explanations + missing fields |
| 10 | Filterable publisher explorer | **RUNTIME** | Production frontend build rendered in Chromium against the 96K-row database; server-side filtering |
| 11 | Complete website intelligence profile | **RUNTIME** | All tabs rendered with fixture-site evidence (screenshots taken during the build) |
| 12 | Export CSV and XLSX | **FIXTURE / RUNTIME** | `test_api.py` parses both formats back. CSV has no comment rows; notes go in the `X-Data-Notes` header and an XLSX "notes" sheet |
| 13 | Display uncertainty and failed scans correctly | **FIXTURE / RUNTIME** | Blocked/failed scans → `SCAN_INCONCLUSIVE` / `UNKNOWN`, never "no ads". Observed for real when the sandbox blocked live sites |
| 14 | Restart safely after worker failure | **RUNTIME** | See [crash-recovery details](#crash-recovery-details) below |
| 15 | Operate without paid API keys | **Yes** | No paid provider is used |

### 100K import details

- **Input:** a 100,000-row CSV built from real CrUX domains, with 2,000 duplicates and 1,000 invalid rows mixed in.
- **Path:** uploaded through the API and imported by a Celery job.
- **Result:** 96,382 websites, a zero diff against an independent normalization of the file, and 1,012 invalid rows reported (matching the offline count).
- **Conditions:** the worker was SIGKILLed mid-import and the task was then delivered twice; the result was unaffected.

### Normalization details

- **Real data:** the real CrUX global list gave 100,000 origins → 99,344 websites.
- **Rejections:** the 10 rejected rows were all correct (public-suffix hosts such as `s3.amazonaws.com`, and underscore hosts).
- **Unit tests:** IDNA, PSL private suffixes (blogspot/github.io stay separate), and www folding.

### Crash-recovery details

- **Jobs:** SIGKILL mid-job, then a restart with a simultaneous Celery redelivery and a watchdog re-queue. A Postgres advisory lock allowed exactly one runner (the duplicate exited with `ALREADY_RUNNING`), and the job finished from its checkpoint.
- **Stages:** leases expire and are reclaimed.
- **Failed rescans:** a failed rescan keeps the previous evidence (tested).

## Bugs found and fixed by these runs

Each of these bugs had passed the unit tests and was caught only by the runtime runs.

- **Long browser errors overflowed a column:** fixed by making it `text`.
- **http-only sites were re-rendered over https after classification:** the origin now keeps the observed scheme.
- **A failed re-render downgraded earlier rendered conclusions:** for example GAM went from active to possible. Rendered conclusions are now kept unless a new render succeeds, and scoring uses the latest *successful* scan.
- **Duplicate hosts in one import batch broke the outreach upsert:** now deduplicated per host.
- **Concurrent duplicate job runs deadlocked:** fixed with an advisory lock, ordered inserts, and deadlock retry.
- **Qualify was too slow (~130 sites/s):** rewritten set-based (~535/s; 110K sites in 3.5 min).
- **The monetization type overstated static-only evidence:** it is now labelled `*_UNCONFIRMED`.

## First live run (your laptop, 2026-10-22)

The infrastructure checks passed on the real internet: outbound HTTPS, robots.txt respected, the SSRF guard (metadata IP, loopback, localhost), CrUX download, and Tranco download. The live run then found three things, all fixed:

- **Google's sellers.json address was wrong.** It is `storage.googleapis.com/adx-rtb-dictionaries/sellers.json` ([Google documentation](https://support.google.com/authorizedbuyers/answer/9895942)). Sources can now name their ad system (`google.com|url`) so records link to `google.com` in ads.txt.
- **bbc.com crashed the classifier.** Its schema.org `@type` is a list. The parser now handles that, and one bad page can no longer crash a batch or the validation run.
- **A database password containing `@` broke the connection.** The URL is now built from escaped parts.

A second live run (10 news sites) showed:

- **Classification:** 7/10 correct, publisher precision 8/8. reuters.com and apnews.com blocked the robot and were correctly reported as UNKNOWN / inconclusive.
- **Ad tech:** GAM active signals on cnn.com, nbcnews.com and independent.co.uk; Prebid active on nbcnews.com.
- **Two problems found and fixed:**
  - **Cookie walls caused false "no ads":** spiegel.de and theguardian.com had 15–19 empty ad containers and no ad calls, because ads were waiting for cookie consent. The renderer now records consent state (CMP globals, visible banners, TCF `gdprApplies` / purpose-1 consent). When every rendered page is consent-gated, key vendors are reported as `SCAN_INCONCLUSIVE` ("ads likely waiting for cookie consent"), never `NOT_OBSERVED`.
  - **theguardian.com was labelled LIFESTYLE:** its menu links to many lifestyle sections. Topic hits are now capped, and a site with news schema that covers several topic areas is classified as news.

What did work in the first run:

- bbc.com was classified as `NEWS_PUBLISHER` and its ads.txt was found.
- reuters.com was reported as robots-disallowed / inconclusive (not "no ads").

## Not built or not working yet

- **Traffic estimates:** removed by request. You research traffic manually; `VERIFIED_HIGH_VALUE` is reachable only through a manual override (with a reason, audited).
- **Metrica:** not integrated. Its Terms of Service (8 Sep 2026) prohibit automated/API access and storing its data. The traffic-provider interface was removed together with traffic.
- **HTTP Archive / BigQuery reverse lookup:** not implemented.
- **Optional LLM classification:** not implemented.
- **Contact discovery (Phase 5):** not implemented. The data model and the "advertise / contact page found" signal exist.
- **Scheduled recheck, change detection and alerts (Phase 6):** not implemented. The `historical_changes` table exists, but nothing writes to it yet. Scheduled *discovery* (CrUX, Tranco, sellers.json) is implemented.
- **OpenTechAnalyzer sidecar:** not integrated. CMS/analytics detection uses the in-house registry. OpenTechAnalyzer (MIT) remains an option.
- **Docker images:** never built in the sandbox (Docker Hub blocked). The Compose file and Dockerfiles must be built on the VPS. The frontend agent also could not build its image.
