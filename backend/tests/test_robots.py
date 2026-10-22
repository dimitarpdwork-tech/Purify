"""robots.txt handling follows RFC 9309 and is matched on our bot token."""
import asyncio

import httpx
import pytest
import respx

from app.core.config import get_settings
from app.services import safe_fetch
from app.services.safe_fetch import SafeFetcher


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    async def fake_resolve(host, port):
        return ["93.184.216.34"]
    monkeypatch.setattr(safe_fetch, "resolve_public", fake_resolve)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _check(robots_response, path="/news/story"):
    async def go():
        with respx.mock(assert_all_called=False) as m:
            m.get("https://site.example/robots.txt").mock(return_value=robots_response)
            m.get(f"https://site.example{path}").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
            async with SafeFetcher() as f:
                return await f.get(f"https://site.example{path}")
    return asyncio.run(go())


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_4xx_robots_means_no_restrictions(status):
    r = _check(httpx.Response(status))
    assert r.ok and not r.blocked


@pytest.mark.parametrize("status", [429, 500, 503])
def test_5xx_and_429_robots_means_disallow(status):
    r = _check(httpx.Response(status))
    assert r.blocked == "robots.txt disallows"


def test_rules_for_our_token_are_respected():
    txt = "User-agent: *\nAllow: /\n\nUser-agent: PurifyPublisherIntelligence\nDisallow: /news/\n"
    assert _check(httpx.Response(200, text=txt)).blocked == "robots.txt disallows"
    assert _check(httpx.Response(200, text=txt), path="/sport/x").ok


def test_wildcard_disallow_applies_to_us():
    assert _check(httpx.Response(200, text="User-agent: *\nDisallow: /\n")).blocked == "robots.txt disallows"


def test_user_agent_uses_standard_bot_format():
    s = get_settings()
    assert s.http_user_agent.startswith("Mozilla/5.0 (compatible; PurifyPublisherIntelligence/")


def test_connection_refused_robots_does_not_mask_the_page_error():
    async def go():
        with respx.mock(assert_all_called=False) as m:
            m.get("https://site.example/robots.txt").mock(side_effect=httpx.ConnectError("refused"))
            m.get("https://site.example/").mock(side_effect=httpx.ConnectError("refused"))
            async with SafeFetcher() as f:
                return await f.get("https://site.example/")
    r = asyncio.run(go())
    assert not r.blocked and r.error and "ConnectError" in r.error


def test_timeout_robots_means_disallow():
    r = _check(httpx.Response(200))  # sanity: reachable robots with empty body allows
    assert r.ok

    async def go():
        with respx.mock(assert_all_called=False) as m:
            m.get("https://site.example/robots.txt").mock(side_effect=httpx.ReadTimeout("slow"))
            m.get("https://site.example/x").mock(return_value=httpx.Response(200, text="ok"))
            async with SafeFetcher() as f:
                return await f.get("https://site.example/x")
    assert asyncio.run(go()).blocked == "robots.txt disallows"
