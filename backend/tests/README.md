# Tests

```bash
export TEST_DATABASE_URL=postgresql+psycopg://purify:purify@localhost:5432/purify_test   # dropped & recreated by the tests
pytest -q
```

Everything here runs on **synthetic fixtures** (`fixtures/html`, `fixtures/vhosts`). Passing tests do
not prove anything about real websites. Use `scripts/live_validate.py` for that.

## End-to-end pipeline test (`test_e2e_pipeline.py`)

This test needs three things; without them it skips:

- Chromium (`CHROMIUM_EXECUTABLE`, or Playwright's bundled browser).
- Fixture hostnames mapped to localhost. Add this line to `/etc/hosts`:
  `127.0.0.1 dailyherald-fixture.com www.dailyherald-fixture.com gamezone-fixture.com www.gamezone-fixture.com acmeshoes-fixture.com www.acmeshoes-fixture.com quickrecipes-fixture.com www.quickrecipes-fixture.com`
- The fixture server on port 80: `sudo python tests/fixtures/vhost_server.py 80`

The gamezone fixture page contains **stub** `googletag` / `pbjs` objects that imitate the public
APIs. It exercises the extraction code and is not real ad tech.
