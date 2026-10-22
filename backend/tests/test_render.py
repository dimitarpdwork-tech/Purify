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


@pytest.fixture(params=["accept"])
def site_server(chromium_available, monkeypatch, request):
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


def _mode(monkeypatch, mode):
    from app.core.config import get_settings

    monkeypatch.setenv("CONSENT_MODE", mode)
    get_settings.cache_clear()


def test_consent_wall_is_inconclusive_not_absent_in_observe_mode(site_server, monkeypatch):
    _mode(monkeypatch, "observe")
    r = _render(site_server + "/consent.html")
    assert r.ok
    c = r.page["consent"]
    assert c["pending"] is True and c["banner_visible"] is True
    assert "sourcepoint" in c["cmps"] and c["tcf"]["gdprApplies"] is True
    res = {v.vendor_key: v for v in detect([_obs(r)])}
    # the page script references GAM statically -> POSSIBLE is correct; the rest must not read as "absent"
    assert res["google_gam"].status == "POSSIBLE"
    for k in ("google_adsense", "prebid", "amazon_aps"):
        assert res[k].status == INCONCLUSIVE, k
        assert "cookie consent" in res[k].detail["reasons"][0]


def test_page_without_cmp_still_detects(site_server):
    r = _render(site_server + "/index.html")
    assert r.ok and r.page["consent"]["pending"] is False
    res = {v.vendor_key: v for v in detect([_obs(r)])}
    assert res["google_gam"].status == ACTIVE and res["prebid"].status == ACTIVE


def test_accept_mode_clicks_accept_not_subscription_and_sees_ads(site_server, monkeypatch):
    _mode(monkeypatch, "accept")
    r = _render(site_server + "/consent.html")
    assert r.ok
    act = r.page["consent_action"]
    assert act["clicked"] and "Akzeptieren" in act["text"] and "Abo" not in act["text"]
    assert r.page["consent"]["pending"] is False and r.page["consent"]["accepted_by_robot"] is True
    res = {v.vendor_key: v for v in detect([_obs(r)])}
    assert res["google_gam"].status == ACTIVE
    assert "accepted the cookie banner" in res["google_gam"].detail["consent"]


def test_accept_mode_handles_sourcepoint_style_iframe(site_server, monkeypatch):
    _mode(monkeypatch, "accept")
    r = _render(site_server + "/consent_iframe.html")
    assert r.page["consent_action"]["clicked"] == "button.sp_choice_type_11"
    res = {v.vendor_key: v for v in detect([_obs(r)])}
    assert res["prebid"].status == ACTIVE and res["pubmatic"].status == ACTIVE


def test_renderer_respects_robots_txt(site_server, monkeypatch, tmp_path):
    """The browser scan must obey robots.txt just like static fetching."""
    from app.core.config import get_settings

    (SITE / "robots.txt").write_text("User-agent: PurifyPublisherIntelligence\nDisallow: /private.html\n")
    try:
        monkeypatch.setenv("RESPECT_ROBOTS_TXT", "true")
        get_settings.cache_clear()
        r = _render(site_server + "/private.html")
        assert r.blocked_reason == "robots.txt disallows" and not r.ok
        assert _render(site_server + "/index.html").ok
    finally:
        (SITE / "robots.txt").unlink()
