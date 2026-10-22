"""Application settings. All secrets are read from the environment (server-side only)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- core ---
    environment: str = "development"
    database_url: str = "postgresql+psycopg://purify:purify@localhost:5432/purify"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = Field(default="change-me", description="JWT signing key")
    access_token_minutes: int = 60 * 12
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    cors_origins: str = "http://localhost:3000"
    data_dir: str = "/data"  # uploads, dataset caches, raw evidence

    # --- crawling policy ---
    user_agent: str = (
        "PurifyPublisherIntelligence/1.0 (+https://purify.digital/bot; publisher research)"
    )
    respect_robots_txt: bool = True
    http_timeout_seconds: float = 15.0
    http_max_bytes: int = 3_000_000
    per_host_min_interval_seconds: float = 2.0
    global_max_concurrent_fetches: int = 32
    max_redirects: int = 5
    # Allow fetching private IPs only in tests / local fixture servers. Never enable in production.
    allow_private_network_fetch: bool = False

    # --- pipeline ---
    classification_max_pages: int = 3
    adtech_max_pages: int = 3
    playwright_enabled: bool = True
    playwright_timeout_ms: int = 25_000
    playwright_settle_ms: int = 6_000
    playwright_concurrency: int = 2
    chromium_executable: str | None = None  # use a system/preinstalled Chromium instead of Playwright's download
    stage_lease_seconds: int = 900
    stage_max_attempts: int = 3
    dispatcher_batch_size: int = 200

    # --- discovery ---
    crux_base_url: str = "https://raw.githubusercontent.com/zakird/crux-top-lists/main/data"
    crux_max_rank_bucket: int = 100_000  # ingest buckets up to this magnitude
    tranco_list_url: str = "https://tranco-list.eu/top-1m.csv.zip"
    tranco_max_rank: int = 200_000
    sellers_json_sources: str = (
        "https://www.google.com/sellers.json,"
        "https://pubmatic.com/sellers.json,"
        "https://cdn.indexexchange.com/sellers.json,"
        "https://openx.com/sellers.json,"
        "https://triplelift.com/sellers.json,"
        "https://sharethrough.com/sellers.json"
    )
    sellers_json_max_bytes: int = 400_000_000

    @property
    def sellers_json_source_list(self) -> list[str]:
        return [s.strip() for s in self.sellers_json_sources.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
