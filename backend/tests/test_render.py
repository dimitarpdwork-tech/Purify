"""Real Chromium against LOCAL fixture pages (stubbed ad tech / CMP). Not evidence about real sites."""
import asyncio
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.adtech.detector import ACTIVE, INCONCLUSIVE, PageObservation, detect

SITE = Path(__file__).parent / "fixtures" / "site"


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture
def site_server(chromium_available, monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_NETWORK_FETCH", "true")
    monkeypatch.setenv("PLAYWRIGHT_SETTLE_MS", "800")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    from app.core.config import get_settings

    get_settings.cache_clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(SITE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    get_settings.cache_clear()


def _render(url):
    from app.adtech.render import Renderer

    async def go():
        async with Renderer() as r:
            return await r.render(url)

    return asyncio.run(go())


def _obs(r):
    return PageObservation(url=r.url, ok=r.ok, rendered=True, html=r.html, script_urls=r.script_urls,
                           network_urls=[n["url"] for n in r.network], globals_present=r.page.get("globals") or {},
                           prebid=r.page.get("prebid") or [], gpt=r.page.get("gpt"), consent=r.page.get("consent"))


def test_consent_wall_is_inconclusive_not_absent(site_server):
    r = _render(site_server + "/consent.html")
    assert r.ok
    c = r.page["consent"]
    assert c["pending"] is True and c["banner_visible"] is True
    assert "sourcepoint" in c["cmps"] and c["tcf"]["gdprApplies"] is True
    res = {v.vendor_key: v for v in detect([_obs(r)])}
    for k in ("google_gam", "google_adsense", "prebid", "amazon_aps"):
        assert res[k].status == INCONCLUSIVE, k
        assert "cookie consent" in res[k].detail["reasons"][0]


def test_page_without_cmp_still_detects(site_server):
    r = _render(site_server + "/index.html")
    assert r.ok and r.page["consent"]["pending"] is False
    res = {v.vendor_key: v for v in detect([_obs(r)])}
    assert res["google_gam"].status == ACTIVE and res["prebid"].status == ACTIVE
