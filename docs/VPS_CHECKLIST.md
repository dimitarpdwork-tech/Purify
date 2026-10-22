# VPS deployment & live-validation checklist

Work through this in order. Write down the result of each check. If a check fails, stop and fix it
before going further.

## 0. Host

- [ ] Ubuntu 22.04/24.04 (or similar), **4 vCPU / 8 GB RAM minimum** (Chromium is the heavy part), 80 GB disk.
- [ ] Docker Engine + Compose plugin: `docker compose version`
- [ ] Outbound HTTPS works: `curl -sI https://example.com | head -1`
- [ ] Ports 8000/3000 are bound to 127.0.0.1 by the Compose file. Put a TLS reverse proxy in front (Caddy or nginx) and expose only 443.

## 1. Configure

```bash
git clone https://github.com/dimitarpdwork-tech/Purify.git && cd Purify
cp .env.example .env
openssl rand -hex 32        # -> SECRET_KEY
openssl rand -hex 24        # -> POSTGRES_PASSWORD
nano .env                   # set SECRET_KEY, POSTGRES_PASSWORD, BOOTSTRAP_ADMIN_*, CORS_ORIGINS, USER_AGENT contact URL
```

- [ ] `ALLOW_PRIVATE_NETWORK_FETCH=false`
- [ ] `USER_AGENT` points at a real page explaining the crawler, with a contact address.

## 2. Build and start

```bash
docker compose build          # first build downloads Chromium via Playwright (~5 min)
docker compose up -d
docker compose ps             # all services "running"/"healthy"
curl -s localhost:8000/api/health   # {"api":"ok","database":"ok","redis":"ok"}
```

- [ ] Migrations ran (the API command runs `alembic upgrade head`): `docker compose logs api | grep -i alembic`
- [ ] Log in at the frontend with `BOOTSTRAP_ADMIN_EMAIL`, then **change the password** (Settings → Users).

## 3. SSRF egress hardening (recommended)

Application-level SSRF checks are on. Also block the workers from reaching private ranges at the
network level:

```bash
# Example with DOCKER-USER chain (adjust the subnet of the compose network: docker network inspect purify_default)
sudo iptables -I DOCKER-USER -s 172.18.0.0/16 -d 169.254.169.254 -j DROP
sudo iptables -I DOCKER-USER -s 172.18.0.0/16 -d 10.0.0.0/8 -j DROP
sudo iptables -I DOCKER-USER -s 172.18.0.0/16 -d 192.168.0.0/16 -j DROP
```

Keep container-to-container traffic (postgres/redis) allowed. Test after applying.

## 4. Live validation (real websites)

```bash
docker compose exec api python -m scripts.live_validate --limit 10      # quick smoke (~3-5 min)
docker compose exec api python -m scripts.live_validate                 # full 110-site benchmark (~30-60 min)
docker compose cp api:/data/validation ./validation-reports
```

Infrastructure checks — **all must PASS** (exit code 0):
- [ ] outbound HTTPS fetch
- [ ] robots.txt respected (google.com/search is disallowed)
- [ ] SSRF guard blocks metadata IP, loopback and localhost
- [ ] CrUX top-list reachable
- [ ] Tranco list reachable
- [ ] sellers.json reachable
- [ ] headless Chromium launches

Review `summary.md`. These are judgement calls, not automatic gates:
- [ ] **Classification:** the expectation is ≥ 80% of benchmark categories correct, and publisher precision ≥ 90%. **Review the ground-truth labels in `backend/benchmark/benchmark_sites.csv`** — I curated them by hand and some are debatable (weather sites, wiki platforms, business news).
- [ ] **UNKNOWN sites:** these are blocked or challenge pages. Confirm in a normal browser that they really block bots; they must **not** show as "no advertising".
- [ ] **Ad-tech, at least 5 large news/entertainment sites:** open the site in Chrome DevTools and compare against `sites/<host>.json`:
  - GPT ad requests (`/gampad/ads`) ↔ `google_gam` = `DETECTED_ACTIVE_SIGNALS`
  - `pbjs.getEvents()` bidders ↔ the report's requested bidders
  - ads.txt record count ↔ the report
- [ ] **Non-publishers:** e-commerce/SaaS/government sites are not classified as publishers.

Send me the `summary.md` (and any wrong cases) so I can tune the rules and fingerprints.

## 5. First real discovery cycle

From the UI (Discovery page) or the API:

1. [ ] `crux_ingest` global, `max_bucket=100000` → ~100K websites (about 2 min).
2. [ ] `crux_ingest` per country you care about (e.g. `us`, `gb`, `de`, `bg`), `max_bucket=10000`.
3. [ ] `tranco_ingest`, `max_rank=100000`.
4. [ ] Optional: `sellers_discovery` (downloads several sellers.json files; Google's is very large).
5. [ ] Watch Dashboard → pipeline stages. Expect `qualify` to finish in minutes, then `classify` (polite: 2 s per host minimum), `supply`, `adtech` (slowest, about 1 site per 10–20 s per render slot), then `score`.
6. [ ] After 24 h, check:
   - [ ] the FAILED rate per stage (Dashboard → recent failures)
   - [ ] the `HIGH_POTENTIAL_VERIFY_TRAFFIC` queue: spot-check 20 profiles by hand
   - [ ] the explorer preset "GAM without header bidding" on the Discovery page

Throughput knobs: Settings → `dispatcher` (batch sizes); the `worker-render` concurrency in
docker-compose.yml; `PLAYWRIGHT_CONCURRENCY`. Scale the render workers up only if CPU and RAM allow.

## 6. Operations

- [ ] Backups: `docker compose exec postgres pg_dump -U purify purify | gzip > backup_$(date +%F).sql.gz` (cron daily).
- [ ] Logs: `docker compose logs -f worker-render worker-fetch`.
- [ ] Pause processing: Settings → dispatcher → `paused: true`.
- [ ] Re-queue failures: Discovery → `requeue_stage` (stage + `FAILED`).
- [ ] Re-score after changing weights: Discovery → `rescore_all` (no re-crawling).
- [ ] Upgrades: `git pull && docker compose build && docker compose up -d` (migrations run on API start).
