"""Administrator-editable settings stored in app_settings, merged over code defaults."""
from __future__ import annotations

import copy
from typing import Any

from app.core.db import session_scope
from app.models import AppSetting


def _defaults() -> dict[str, Any]:
    from app.scoring.score import DEFAULT_WEIGHTS

    return {
        "scoring_weights": DEFAULT_WEIGHTS,
        # Popularity gate for the cheap qualify stage. Websites outside it are SKIPPED (not deleted)
        # and re-queued automatically if newer popularity data puts them inside.
        "qualification": {"max_crux_bucket": 100000, "max_tranco_rank": 100000, "max_country_crux_bucket": 10000},
        "dispatcher": {"classify_batch": 40, "supply_batch": 40, "adtech_batch": 6, "score_batch": 200, "qualify_batch": 1000,
                       "paused": False},
        "schedules": {
            "crux_global": {"enabled": True, "cron": "0 3 15 * *", "params": {"max_bucket": 100000}},
            "crux_countries": {"enabled": True, "cron": "0 4 15 * *",
                               "params": {"countries": ["us", "gb", "de", "fr", "ca", "au", "nl", "se", "it", "es", "pl", "bg", "ro"],
                                          "max_bucket": 10000}},
            "tranco": {"enabled": True, "cron": "0 2 * * 1", "params": {"max_rank": 100000}},
            "sellers_json": {"enabled": False, "cron": "0 5 1 * *", "params": {}},
        },
    }


def _merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        out = copy.deepcopy(base)
        for k, v in over.items():
            out[k] = _merge(base.get(k), v) if k in base else v
        return out
    return copy.deepcopy(over) if over is not None else copy.deepcopy(base)


def get_setting(key: str) -> Any:
    defaults = _defaults()
    with session_scope() as s:
        row = s.get(AppSetting, key)
        stored = row.value if row else None
    if key in defaults:
        return _merge(defaults[key], stored) if stored is not None else copy.deepcopy(defaults[key])
    return stored


def set_setting(key: str, value: Any, user_id: int | None = None) -> Any:
    with session_scope() as s:
        row = s.get(AppSetting, key)
        if row:
            row.value = value
            row.updated_by = user_id
        else:
            s.add(AppSetting(key=key, value=value, updated_by=user_id))
    return get_setting(key)


def all_settings() -> dict[str, Any]:
    return {k: get_setting(k) for k in _defaults()}
