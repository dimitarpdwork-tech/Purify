"""sellers.json (IAB Tech Lab 1.0) streaming parser.

Large files (Google's is hundreds of MB) are parsed incrementally from disk so memory stays
bounded. Entries are yielded as dicts; publisher-type entries with a domain are discovery leads.
"""
from __future__ import annotations

import json
from typing import Any, Iterator

SELLER_TYPES = {"PUBLISHER", "INTERMEDIARY", "BOTH"}


def normalize_entry(e: dict[str, Any]) -> dict[str, Any] | None:
    sid = e.get("seller_id")
    if sid is None:
        return None
    st = str(e.get("seller_type") or "").upper() or None
    return {
        "seller_id": str(sid)[:200],
        "name": (str(e["name"])[:500] if e.get("name") else None),
        "domain": (str(e["domain"]).strip().lower()[:253] if e.get("domain") else None),
        "seller_type": st if st in SELLER_TYPES else st,
        "is_confidential": bool(e.get("is_confidential") in (1, True, "1", "true")),
    }


def iter_sellers_from_text(text: str) -> Iterator[dict[str, Any]]:
    data = json.loads(text)
    for e in data.get("sellers") or []:
        n = normalize_entry(e) if isinstance(e, dict) else None
        if n:
            yield n


def iter_sellers_from_file(path: str, chunk_size: int = 1 << 20) -> Iterator[dict[str, Any]]:
    """Incrementally decode objects inside the top-level "sellers" array."""
    dec = json.JSONDecoder()
    buf = ""
    in_array = False
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk and not buf:
                break
            buf += chunk
            if not in_array:
                idx = buf.find('"sellers"')
                if idx < 0:
                    if not chunk:
                        break
                    buf = buf[-20:]
                    continue
                br = buf.find("[", idx)
                if br < 0:
                    if not chunk:
                        break
                    continue
                buf = buf[br + 1:]
                in_array = True
            pos = 0
            while True:
                while pos < len(buf) and buf[pos] in " \t\r\n,":
                    pos += 1
                if pos < len(buf) and buf[pos] == "]":
                    return
                try:
                    obj, end = dec.raw_decode(buf, pos)
                except json.JSONDecodeError:
                    break
                pos = end
                if isinstance(obj, dict):
                    n = normalize_entry(obj)
                    if n:
                        yield n
            buf = buf[pos:]
            if not chunk:
                break
