"""Downloading and streaming public popularity datasets (CrUX top lists, Tranco).

CrUX (via github.com/zakird/crux-top-lists): origins bucketed by rank magnitude
(1k, 5k, 10k, 50k, 100k, 500k, 1M). Buckets are coarse popularity bands, NOT ranks and NOT
traffic volumes; within a bucket order is random.
Tranco (tranco-list.eu): research ranking aggregated from several lists; a rank, NOT traffic.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import math
import os
import zipfile
from pathlib import Path
from typing import Iterator

import httpx

from app.core.config import get_settings

CRUX_BUCKETS = (1000, 5000, 10000, 50000, 100000, 500000, 1000000)


def _cache_dir() -> Path:
    p = Path(get_settings().data_dir) / "datasets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def download(url: str, dest: Path, max_bytes: int = 600_000_000, timeout: float = 300.0) -> Path:
    """Stream a public dataset to disk (resumes nothing; atomically renames on success)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": get_settings().http_user_agent}) as r:
        r.raise_for_status()
        size = 0
        with open(tmp, "wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"dataset larger than {max_bytes} bytes: {url}")
                fh.write(chunk)
    os.replace(tmp, dest)
    return dest


def crux_url(period: str, country: str | None = None) -> str:
    base = get_settings().crux_base_url.rstrip("/")
    if country:
        return f"{base}/country/{country.lower()}/{period}.csv.gz"
    return f"{base}/global/{period}.csv.gz"


def crux_latest_period(country: str | None = None, max_months_back: int = 4) -> str:
    """Find the newest published monthly file by probing backwards from the current month."""
    today = dt.date.today()
    y, m = today.year, today.month
    for _ in range(max_months_back + 1):
        period = f"{y}{m:02d}"
        try:
            r = httpx.head(crux_url(period, country), timeout=20, follow_redirects=True)
            if r.status_code == 200:
                return period
        except httpx.HTTPError:
            pass
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    raise RuntimeError(f"no CrUX file found for country={country or 'global'} in the last {max_months_back} months")


def fetch_crux(period: str, country: str | None = None) -> tuple[Path, str]:
    url = crux_url(period, country)
    dest = _cache_dir() / f"crux_{country or 'global'}_{period}.csv.gz"
    if not dest.exists():
        download(url, dest)
    return dest, url


def iter_crux(path: Path, max_bucket: int) -> Iterator[tuple[int, str, int]]:
    """Yields (row_number, origin, rank_bucket) for buckets <= max_bucket. File is bucket-ordered."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header or header[0].strip().lower() != "origin":
            raise ValueError(f"unexpected CrUX header {header}")
        for i, row in enumerate(reader, start=1):
            if len(row) < 2:
                continue
            try:
                bucket = int(row[1])
            except ValueError:
                continue
            if bucket > max_bucket:
                break  # sorted by bucket magnitude
            yield i, row[0].strip(), bucket


def tranco_list_id() -> str | None:
    try:
        r = httpx.get("https://tranco-list.eu/top-1m-id", timeout=20, follow_redirects=True)
        if r.status_code == 200 and len(r.text.strip()) < 20:
            return r.text.strip()
    except httpx.HTTPError:
        return None
    return None


def fetch_tranco() -> tuple[Path, str, str]:
    list_id = tranco_list_id() or dt.date.today().isoformat()
    url = get_settings().tranco_list_url
    dest = _cache_dir() / f"tranco_{list_id}.csv.zip"
    if not dest.exists():
        download(url, dest)
    return dest, url, list_id


def iter_tranco(path: Path, max_rank: int) -> Iterator[tuple[int, str, int]]:
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".csv"))
        with zf.open(name) as raw:
            for i, line in enumerate(io.TextIOWrapper(raw, encoding="utf-8"), start=1):
                parts = line.strip().split(",")
                if len(parts) < 2:
                    continue
                try:
                    rank = int(parts[0])
                except ValueError:
                    continue
                if rank > max_rank:
                    break
                yield i, parts[1].strip(), rank


def popularity_priority(crux_bucket: int | None = None, tranco_rank: int | None = None) -> float:
    """Ordering heuristic for processing queues only. It is not a traffic estimate."""
    p = 0.0
    if crux_bucket:
        p = max(p, {1000: 100, 5000: 92, 10000: 85, 50000: 70, 100000: 60, 500000: 40, 1000000: 25}.get(crux_bucket, 20))
    if tranco_rank:
        p = max(p, max(0.0, 95 - 15 * math.log10(max(tranco_rank, 1))))
    return round(p, 2)
