"""Standards-aware ads.txt parser (IAB Tech Lab ads.txt 1.1).

Record:   <ad system domain>, <seller account id>, <DIRECT|RESELLER>[, <certification authority id>]
Variable: <NAME>=<value>   (CONTACT, SUBDOMAIN, INVENTORYPARTNERDOMAIN, OWNERDOMAIN, MANAGERDOMAIN)
Comments start with '#'; extension fields after ';' are ignored. Malformed lines are kept
(with a reason) rather than dropped silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

KNOWN_VARIABLES = {"CONTACT", "SUBDOMAIN", "INVENTORYPARTNERDOMAIN", "OWNERDOMAIN", "MANAGERDOMAIN"}
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$")
_VAR_RE = re.compile(r"^([A-Za-z]+)\s*=\s*(.*)$")


@dataclass
class AdsTxtRecord:
    ad_system_domain: str
    seller_account_id: str
    relationship: str
    cert_authority_id: str | None
    line_no: int


@dataclass
class ParsedAdsTxt:
    records: list[AdsTxtRecord] = field(default_factory=list)
    variables: dict[str, list[str]] = field(default_factory=dict)
    malformed: list[dict] = field(default_factory=list)
    duplicate_count: int = 0

    @property
    def owner_domain(self) -> str | None:
        v = self.variables.get("OWNERDOMAIN")
        return v[0] if v else None

    @property
    def manager_domains(self) -> list[str]:
        return self.variables.get("MANAGERDOMAIN", [])

    @property
    def subdomains(self) -> list[str]:
        return self.variables.get("SUBDOMAIN", [])


def looks_like_html(text: str) -> bool:
    head = text.lstrip()[:500].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<head" in head or "<body" in head


def parse(text: str, max_lines: int = 200_000) -> ParsedAdsTxt:
    out = ParsedAdsTxt()
    seen: set[tuple] = set()
    text = text.lstrip("﻿")
    for i, raw in enumerate(text.splitlines()[:max_lines], start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # extension fields
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        if "," not in line:
            m = _VAR_RE.match(line)
            if m and m.group(1).upper() in KNOWN_VARIABLES:
                out.variables.setdefault(m.group(1).upper(), []).append(m.group(2).strip())
            elif m:
                out.variables.setdefault(m.group(1).upper(), []).append(m.group(2).strip())
            else:
                out.malformed.append({"line": i, "text": raw[:300], "reason": "not a record or variable"})
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            out.malformed.append({"line": i, "text": raw[:300], "reason": "fewer than 3 fields"})
            continue
        domain = parts[0].lower().rstrip(".")
        if domain.startswith("http://") or domain.startswith("https://"):
            domain = domain.split("://", 1)[1].split("/", 1)[0]
        if domain.startswith("www."):
            domain = domain[4:]
        account = parts[1].strip()
        rel = parts[2].strip().upper()
        cert = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None
        if not _DOMAIN_RE.match(domain):
            out.malformed.append({"line": i, "text": raw[:300], "reason": "invalid ad system domain"})
            continue
        if not account:
            out.malformed.append({"line": i, "text": raw[:300], "reason": "empty seller account id"})
            continue
        if rel not in ("DIRECT", "RESELLER"):
            out.malformed.append({"line": i, "text": raw[:300], "reason": f"invalid relationship {parts[2]!r}"})
            continue
        key = (domain, account.lower(), rel)
        if key in seen:
            out.duplicate_count += 1
            continue
        seen.add(key)
        out.records.append(AdsTxtRecord(domain, account[:200], rel, cert[:100] if cert else None, i))
    return out
