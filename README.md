# Purify Publisher Intelligence

Discovers websites, classifies advertising-supported publishers, inspects their ad-tech stacks
(GAM, AdSense, Prebid, APS, SSPs, managed partners), parses ads.txt / sellers.json, and ranks
evidence-backed monetization opportunities for Purify Digital.

**Status:** Phases 1–4, without traffic estimates (you research traffic manually). See
[docs/VERIFICATION.md](docs/VERIFICATION.md) for what was tested, and how. Real-website behaviour
must be confirmed on the VPS with `scripts/live_validate.py`
([docs/VPS_CHECKLIST.md](docs/VPS_CHECKLIST.md)).

## Quick start (Docker)

```bash
cp .env.example .env   # set SECRET_KEY, POSTGRES_PASSWORD, BOOTSTRAP_ADMIN_* ...
docker compose up -d --build
open http://localhost:3000
```

From the Discovery page, run `crux_ingest`, then `tranco_ingest`. The pipeline then runs by itself
(qualify → classify → ads.txt → render → score). Scheduled discovery (CrUX monthly, Tranco weekly)
is configurable under Settings → schedules.

## Local development

```bash
# backend
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt && python -m playwright install chromium
export DATABASE_URL=postgresql+psycopg://purify:purify@localhost:5432/purify DATA_DIR=./data SECRET_KEY=dev \
       BOOTSTRAP_ADMIN_EMAIL=admin@local.test BOOTSTRAP_ADMIN_PASSWORD=dev-password-123
alembic upgrade head
uvicorn app.main:app --reload                                        # API on :8000
celery -A app.worker worker -Q jobs,fast,fetch,render -c 3           # workers
celery -A app.worker beat                                            # dispatcher + schedules
# frontend
cd frontend && npm install && npm run dev                            # UI on :3000 (proxies /api to :8000)
```

Tests: `cd backend && pytest` (needs a Postgres test DB, `TEST_DATABASE_URL`). The end-to-end
pipeline test also needs Chromium and the fixture vhost server (see `backend/tests/README.md`).

## Layout

```
backend/app/
  adtech/       fingerprints.yaml (vendor registry), detector.py (evidence -> statuses), render.py (Playwright)
  classify/     features.py (page features), rules.py (deterministic publisher classifier)
  supply/       adstxt.py, sellersjson.py (IAB parsers)
  discovery/    datasets.py (CrUX/Tranco download + streaming)
  jobs/         resumable jobs: imports, dataset ingestion, sellers.json discovery, rescoring
  pipeline/     stage claiming/leases, exclusions, stage implementations
  scoring/      opportunity.py (A–G hypotheses), score.py (0–100 + queues)
  api/          REST API (34 endpoints)
backend/scripts/live_validate.py    live validation against real websites
backend/benchmark/benchmark_sites.csv  110-site hand-labelled benchmark (please review labels)
frontend/       Next.js UI (dashboard, explorer, profile, discovery, import, pipeline, settings)
docs/           ARCHITECTURE.md, VERIFICATION.md, VPS_CHECKLIST.md
```
