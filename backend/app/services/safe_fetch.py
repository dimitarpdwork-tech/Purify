"""SSRF-safe, polite HTTP fetching for public website inspection.

Every request (including each redirect hop):
* must be http/https on the default ports (80/443);
* must resolve exclusively to public unicast IP addresses (private, loopback, link-local,
  metadata, CGNAT, multicast and reserved ranges are refused);
* respects robots.txt for our user agent when enabled;
* is rate limited per host and globally, size-capped and time-limited.

Residual risk: DNS can change between validation and connect (rebinding). In production
the worker containers additionally run on a network with egress to RFC1918 ranges blocked
(see deploy/README). Never run with ALLOW_PRIVATE_NETWORK_FETCH=true in production.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import get_settings

_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
        "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16",
        "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
        "255.255.255.255/32", "::/128", "::1/128", "::ffff:0:0/96", "64:ff9b::/96", "100::/64",
        "2001:db8::/32", "fc00::/7", "fe80::/10", "ff00::/8",
    )
]
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata", "instance-data"}


class FetchBlocked(Exception):
    """Request refused by policy (SSRF guard, robots.txt, scheme...)."""


def ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if any(addr in net for net in _BLOCKED_NETWORKS if net.version == addr.version):
        return False
    return addr.is_global


async def resolve_public(host: str, port: int) -> list[str]:
    settings = get_settings()
    h = host.lower().rstrip(".")
    if h in _BLOCKED_HOSTNAMES or h.endswith(".internal") or h.endswith(".local") or h.endswith(".localhost"):
        if not settings.allow_private_network_fetch:
            raise FetchBlocked(f"hostname not allowed: {host}")
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(h, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise httpx.ConnectError(f"DNS resolution failed for {host}: {exc}") from exc
    ips = sorted({info[4][0] for info in infos})
    if not ips:
        raise httpx.ConnectError(f"no addresses for {host}")
    if not settings.allow_private_network_fetch:
        bad = [ip for ip in ips if not ip_is_public(ip)]
        if bad:
            raise FetchBlocked(f"{host} resolves to non-public address(es) {bad}")
    return ips


def validate_url(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise FetchBlocked(f"scheme not allowed: {scheme!r}")
    if parts.username or parts.password:
        raise FetchBlocked("credentials in URL not allowed")
    host = parts.hostname
    if not host:
        raise FetchBlocked("URL has no host")
    port = parts.port or (443 if scheme == "https" else 80)
    if port not in (80, 443) and not get_settings().allow_private_network_fetch:
        raise FetchBlocked(f"port not allowed: {port}")
    return scheme, host, port


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None
    content_type: str | None
    body: bytes
    redirects: list[str] = field(default_factory=list)
    error: str | None = None
    blocked: str | None = None  # policy refusal reason
    truncated: bool = False
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and self.blocked is None and self.status is not None and 200 <= self.status < 300

    def text(self) -> str:
        enc = "utf-8"
        if self.content_type and "charset=" in self.content_type.lower():
            enc = self.content_type.lower().split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(enc, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class _HostThrottle:
    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            delta = now - self._last.get(host, 0.0)
            if delta < self.min_interval:
                await asyncio.sleep(self.min_interval - delta)
            self._last[host] = time.monotonic()


class SafeFetcher:
    """Async fetcher. Create one per batch: `async with SafeFetcher() as f: ...`."""

    def __init__(self, *, respect_robots: bool | None = None, max_bytes: int | None = None) -> None:
        s = get_settings()
        self.settings = s
        self.respect_robots = s.respect_robots_txt if respect_robots is None else respect_robots
        self.max_bytes = max_bytes or s.http_max_bytes
        self._throttle = _HostThrottle(s.per_host_min_interval_seconds)
        self._sem = asyncio.Semaphore(s.global_max_concurrent_fetches)
        self._robots: dict[str, RobotFileParser | None] = {}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "SafeFetcher":
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(self.settings.http_timeout_seconds),
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
                "Accept-Language": "en;q=0.8,*;q=0.5",
            },
            http2=False,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------ robots
    async def allowed_by_robots(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc}"
        if key not in self._robots:
            rp: RobotFileParser | None = None
            res = await self._raw_get(urljoin(key, "/robots.txt"), max_bytes=500_000, check_robots=False)
            if res.status and 200 <= res.status < 300 and not res.error:
                rp = RobotFileParser()
                rp.parse(res.text().splitlines())
            elif res.status in (401, 403):
                rp = RobotFileParser()
                rp.disallow_all = True
            # 404 / errors -> treat as no restrictions (RFC 9309 sec. 2.3.1.3)
            self._robots[key] = rp
        rp = self._robots[key]
        if rp is None:
            return True
        return rp.can_fetch(self.settings.user_agent, url)

    # ------------------------------------------------------------------ fetching
    async def get(self, url: str, *, max_bytes: int | None = None, check_robots: bool = True) -> FetchResult:
        return await self._raw_get(url, max_bytes=max_bytes or self.max_bytes, check_robots=check_robots)

    async def _raw_get(self, url: str, *, max_bytes: int, check_robots: bool) -> FetchResult:
        assert self._client is not None, "use `async with SafeFetcher()`"
        start = time.monotonic()
        redirects: list[str] = []
        current = url
        for _hop in range(self.settings.max_redirects + 1):
            try:
                _scheme, host, port = validate_url(current)
                await resolve_public(host, port)
                if check_robots and not await self.allowed_by_robots(current):
                    return FetchResult(url, current, None, None, b"", redirects, blocked="robots.txt disallows",
                                       elapsed_ms=int((time.monotonic() - start) * 1000))
            except FetchBlocked as exc:
                return FetchResult(url, current, None, None, b"", redirects, blocked=str(exc),
                                   elapsed_ms=int((time.monotonic() - start) * 1000))
            except httpx.HTTPError as exc:
                return FetchResult(url, current, None, None, b"", redirects, error=str(exc),
                                   elapsed_ms=int((time.monotonic() - start) * 1000))

            await self._throttle.wait(host)
            try:
                async with self._sem:
                    async with self._client.stream("GET", current) as resp:
                        if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                            nxt = urljoin(current, resp.headers["location"])
                            redirects.append(nxt)
                            current = nxt
                            continue
                        body = bytearray()
                        truncated = False
                        async for chunk in resp.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > max_bytes:
                                truncated = True
                                del body[max_bytes:]
                                break
                        return FetchResult(
                            url, str(resp.url), resp.status_code, resp.headers.get("content-type"), bytes(body),
                            redirects, truncated=truncated, elapsed_ms=int((time.monotonic() - start) * 1000),
                        )
            except httpx.HTTPError as exc:
                return FetchResult(url, current, None, None, b"", redirects, error=f"{type(exc).__name__}: {exc}",
                                   elapsed_ms=int((time.monotonic() - start) * 1000))
        return FetchResult(url, current, None, None, b"", redirects, error="too many redirects",
                           elapsed_ms=int((time.monotonic() - start) * 1000))
