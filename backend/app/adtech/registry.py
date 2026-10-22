"""Loads the fingerprint registry (YAML) into compiled matchers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).with_name("fingerprints.yaml")

AD_CATEGORIES = {
    "ad_server", "adsense", "declared_google", "header_bidding", "ssp", "native", "video",
    "monetization_partner", "yield_analytics",
}


@dataclass
class Vendor:
    key: str
    name: str
    category: str
    script: list[re.Pattern] = field(default_factory=list)
    network: list[re.Pattern] = field(default_factory=list)
    html: list[re.Pattern] = field(default_factory=list)
    globals: list[str] = field(default_factory=list)
    ads_txt: list[str] = field(default_factory=list)
    bidders: list[str] = field(default_factory=list)

    @property
    def is_ad_tech(self) -> bool:
        return self.category in AD_CATEGORIES

    @property
    def needs_render(self) -> bool:
        """Vendors whose execution can only be confirmed in a rendered page."""
        return bool(self.network or self.globals or self.bidders)


@dataclass
class Registry:
    version: str
    vendors: list[Vendor]
    by_key: dict[str, Vendor]
    ads_txt_index: dict[str, str]  # ad system domain -> vendor key
    bidder_index: dict[str, str]  # prebid bidder code (lower) -> vendor key

    def vendor_for_ad_system(self, domain: str) -> str | None:
        d = (domain or "").strip().lower().rstrip(".")
        if d.startswith("www."):
            d = d[4:]
        return self.ads_txt_index.get(d)

    def vendor_for_bidder(self, code: str) -> str | None:
        return self.bidder_index.get((code or "").lower())

    def all_globals(self) -> list[str]:
        out: list[str] = []
        for v in self.vendors:
            out.extend(v.globals)
        return sorted(set(out))


def _c(patterns: list[str] | None) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in (patterns or [])]


@lru_cache
def load_registry(path: str | None = None) -> Registry:
    data = yaml.safe_load(Path(path or REGISTRY_PATH).read_text())
    vendors: list[Vendor] = []
    for v in data["vendors"]:
        vendors.append(
            Vendor(
                key=v["key"], name=v["name"], category=v["category"],
                script=_c(v.get("script")), network=_c(v.get("network")), html=_c(v.get("html")),
                globals=list(v.get("globals") or []),
                ads_txt=[d.lower() for d in (v.get("ads_txt") or [])],
                bidders=[b.lower() for b in (v.get("bidders") or [])],
            )
        )
    keys = [v.key for v in vendors]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate vendor keys in fingerprint registry")
    ads_idx: dict[str, str] = {}
    bid_idx: dict[str, str] = {}
    for v in vendors:
        for d in v.ads_txt:
            ads_idx.setdefault(d, v.key)
        for b in v.bidders:
            bid_idx.setdefault(b, v.key)
    return Registry(str(data.get("version")), vendors, {v.key: v for v in vendors}, ads_idx, bid_idx)
