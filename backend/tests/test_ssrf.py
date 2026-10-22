import asyncio

import pytest

from app.core.config import get_settings
from app.services.safe_fetch import FetchBlocked, SafeFetcher, ip_is_public, resolve_public, validate_url


@pytest.fixture(autouse=True)
def strict(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_NETWORK_FETCH", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
                                "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "224.0.0.1"])
def test_private_ips_blocked(ip):
    assert not ip_is_public(ip)


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_ips_allowed(ip):
    assert ip_is_public(ip)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x.com/", "ftp://x.com/", "http://user:pw@x.com/", "http://x.com:6379/"])
def test_bad_urls(url):
    with pytest.raises(FetchBlocked):
        validate_url(url)


@pytest.mark.parametrize("host", ["localhost", "metadata.google.internal", "foo.internal", "printer.local"])
def test_internal_hostnames_blocked(host):
    with pytest.raises(FetchBlocked):
        asyncio.run(resolve_public(host, 80))


def test_fetcher_refuses_loopback_and_metadata():
    async def go():
        async with SafeFetcher(respect_robots=False) as f:
            return [await f.get(u) for u in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/")]

    for r in asyncio.run(go()):
        assert r.blocked and not r.ok


def test_redirect_to_private_is_blocked(monkeypatch):
    """A public-looking hop that redirects to an internal address must be refused at the redirect hop."""
    import httpx
    import respx

    from app.services import safe_fetch

    async def fake_resolve(host, port):
        if host == "public.example":
            return ["93.184.216.34"]
        raise FetchBlocked(f"{host} resolves to non-public address")

    monkeypatch.setattr(safe_fetch, "resolve_public", fake_resolve)

    async def go():
        with respx.mock(assert_all_called=False) as m:
            m.get("http://public.example/").mock(return_value=httpx.Response(302, headers={"location": "http://internal.example/admin"}))
            async with SafeFetcher(respect_robots=False) as f:
                return await f.get("http://public.example/")

    r = asyncio.run(go())
    assert r.blocked and "non-public" in r.blocked
    assert r.redirects == ["http://internal.example/admin"]
