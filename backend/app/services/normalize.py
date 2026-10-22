"""Domain / origin normalisation.

* IDNA (UTS-46) normalisation of hostnames.
* Public Suffix List (bundled snapshot, private section included) to find the registrable
  domain. Including PSL *private* suffixes means `alice.blogspot.com` and `bob.blogspot.com`
  are separate registrable domains - publishers on shared platforms are never merged.
* A leading `www.` is folded into the bare host for identity; every other subdomain is kept
  as a distinct website.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import idna
import tldextract

# Offline: use the snapshot bundled with tldextract, never fetch the PSL at runtime.
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True, cache_dir=None)

_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


class NormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedHost:
    host: str  # identity key: lowercase, IDNA (punycode), no leading www.
    observed_host: str  # host as given (www kept)
    registrable_domain: str
    public_suffix: str
    is_private_suffix: bool
    original: str

    @property
    def origin(self) -> str:
        return f"https://{self.observed_host}"

    @property
    def is_subdomain(self) -> bool:
        return self.host != self.registrable_domain


def _to_ascii(host: str) -> str:
    host = host.strip().strip(".").lower()
    if not host:
        raise NormalizationError("empty host")
    try:
        return idna.encode(host, uts46=True, transitional=False).decode("ascii")
    except idna.IDNAError:
        # idna is strict about some legacy labels (e.g. underscores); fall back to the
        # Python codec and let validation below decide.
        try:
            return host.encode("idna").decode("ascii")
        except UnicodeError as exc:  # pragma: no cover - defensive
            raise NormalizationError(f"invalid IDN host: {host!r}") from exc


def extract_host(raw: str) -> str:
    """Pull a hostname out of a URL, bare domain, or `host:port/path` string."""
    value = (raw or "").strip().strip('"').strip("'")
    if not value:
        raise NormalizationError("empty value")
    if "@" in value.split("/")[0]:
        raise NormalizationError("looks like an email address, not a website")
    if not _SCHEME_RE.match(value):
        value = "http://" + value.lstrip("/")
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https"):
        raise NormalizationError(f"unsupported scheme: {parts.scheme}")
    host = parts.hostname or ""
    if not host:
        raise NormalizationError(f"no host in {raw!r}")
    return host


def normalize(raw: str) -> NormalizedHost:
    host = _to_ascii(extract_host(raw))
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False
    if is_ip:
        raise NormalizationError("IP addresses are not websites")
    labels = host.split(".")
    if len(labels) < 2 or len(host) > 253:
        raise NormalizationError(f"not a fully qualified domain: {host!r}")
    for label in labels:
        if not _LABEL_RE.match(label):
            raise NormalizationError(f"invalid label {label!r} in {host!r}")

    ext = _EXTRACT(host)
    if not ext.suffix:
        raise NormalizationError(f"unknown public suffix: {host!r}")
    if not ext.domain:
        raise NormalizationError(f"host is a public suffix: {host!r}")
    registrable = f"{ext.domain}.{ext.suffix}"

    identity = host
    if identity.startswith("www.") and identity[4:] != ext.suffix and len(identity) > len(registrable) - 1:
        stripped = identity[4:]
        # only strip when the remainder is still at or below a registrable domain
        if stripped.endswith(registrable):
            identity = stripped

    is_private = bool(getattr(ext, "is_private", False))
    return NormalizedHost(
        host=identity,
        observed_host=host,
        registrable_domain=registrable,
        public_suffix=ext.suffix,
        is_private_suffix=is_private,
        original=raw,
    )


def try_normalize(raw: str) -> tuple[NormalizedHost | None, str | None]:
    try:
        return normalize(raw), None
    except NormalizationError as exc:
        return None, str(exc)


def same_site(host_a: str, host_b: str) -> bool:
    """True when two hosts share a registrable domain (used for redirect checks)."""
    a, b = try_normalize(host_a)[0], try_normalize(host_b)[0]
    return bool(a and b and a.registrable_domain == b.registrable_domain)
