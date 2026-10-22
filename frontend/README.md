# Purify Publisher Intelligence: frontend

Next.js (App Router) + TypeScript + Tailwind UI for the Purify Publisher Intelligence API
(`../backend`). Every page reads live data from the API; there is no mock data.

## Development

```bash
npm install
API_INTERNAL_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

The browser only ever calls relative `/api/...` URLs. `next.config.mjs` rewrites
`/api/:path*` to `${API_INTERNAL_URL}/api/:path*`, so no CORS setup is needed.

Sign in with a backend user (create the first admin with the backend's
`BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD`). The bearer token is kept in
`localStorage`; any 401 sends you back to `/login`.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `API_INTERNAL_URL` | `http://localhost:8000` | Backend base URL (without `/api`). **Read at build time**: Next.js compiles rewrites into the build, so set it before `npm run build` / `docker build`. |
| `PORT` | `3000` | Port for `next start` / the standalone server. |
| `HOSTNAME` | `0.0.0.0` (Docker) | Interface the standalone server binds to. |

## Scripts

```bash
npm run build      # production build (output: "standalone")
npm run start      # serve the build with next start
npm run lint       # eslint (flat config, next/core-web-vitals + typescript)
npm run typecheck  # tsc --noEmit
```

To run the standalone output without Docker, copy the static assets next to it first:

```bash
cp -r .next/static .next/standalone/.next/ && cp -r public .next/standalone/
node .next/standalone/server.js
```

## Docker

```bash
docker build --build-arg API_INTERNAL_URL=http://api:8000 -t purify-frontend .
docker run -p 3000:3000 purify-frontend
```

## Layout

```
src/app/login                 sign in
src/app/(app)/page.tsx        dashboard
src/app/(app)/explorer        publisher explorer (server-side filter/sort/paginate, views, bulk, export)
src/app/(app)/websites/[id]   website intelligence profile
src/app/(app)/discovery       discovery jobs + query builder
src/app/(app)/import          CSV/XLSX import center
src/app/(app)/pipeline        outreach board
src/app/(app)/settings        settings, exclusions, users, audit log
src/components                UI primitives (ui.tsx), domain badges, charts, shared tables
src/lib                       API client, types mirroring backend/app/api/routes.py, vocabulary
```

## Product rules encoded in the UI

- No traffic or visits figures. Popularity is shown as the CrUX bucket (a band, e.g. "Top 10K") and the
  Tranco rank, always labelled as popularity.
- Ad-tech statuses have distinct badges (colour plus glyph) and tooltips:
  Active signals / Possible / ads.txt only / Not observed / Inconclusive. Missing results show "not scanned".
- Opportunity types A–G and queues are shown with their labels; `VERIFIED_HIGH_VALUE` can only be set
  through a manual queue override, which requires a reason.
