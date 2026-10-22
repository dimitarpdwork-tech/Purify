"""Application settings. All secrets are read from the environment (server-side only)."""
from __future__ import annotations

from functools import lru_cache

from urllib.parse import quote

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- core ---
    environment: str = "development"
    database_url: str = "postgresql+psycopg://purify:purify@localhost:5432/purify"
    # Alternative to DATABASE_URL: give the parts and the URL is built with proper escaping, so
    # passwords may contain @ : / # ! etc. (used by docker-compose).
    postgres_host: str | None = None
    postgres_port: int = 5432
    postgres_user: str = "purify"
    postgres_password: str | None = None
    postgres_db: str = "purify"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = Field(default="change-me", description="JWT signing key")
    access_token_minutes: int = 60 * 12
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    cors_origins: str = "http://localhost:3000"
    data_dir: str = "/data"  # uploads, dataset caches, raw evidence

    # --- crawling policy ---
    # Bot identity. Sent to websites in the standard crawler format
    # "Mozilla/5.0 (compatible; <user_agent>)" (static fetches) and appended to the browser's own
    # user agent (rendered scans). robots.txt rules are matched on `robots_token`.
    user_agent: str = "PurifyPublisherIntelligence/1.0 (+https://purify.digital/bot; publisher research)"
    robots_token: str = "PurifyPublisherIntelligence"
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
    # "accept": click "Accept" on cookie-consent banners in the robot's own browser so EU ad stacks load
    # (recorded in evidence). "observe": never click; consent-walled pages become SCAN_INCONCLUSIVE.
    consent_mode: str = "accept"
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
        "google.com|https://storage.googleapis.com/adx-rtb-dictionaries/sellers.json,"
        "https://pubmatic.com/sellers.json,"
        "https://cdn.indexexchange.com/sellers.json,"
        "https://openx.com/sellers.json,"
        "https://triplelift.com/sellers.json,"
        "https://sharethrough.com/sellers.json"
    )
    sellers_json_max_bytes: int = 400_000_000

    @property
    def http_user_agent(self) -> str:
        ua = self.user_agent.strip()
        return ua if ua.lower().startswith("mozilla/") else f"Mozilla/5.0 (compatible; {ua})"

    @model_validator(mode="after")
    def _build_database_url(self) -> "Settings":
        if self.postgres_host and "database_url" not in self.model_fields_set:
            pw = quote(self.postgres_password or "", safe="")
            self.database_url = (f"postgresql+psycopg://{quote(self.postgres_user, safe='')}:{pw}"
                                 f"@{self.postgres_host}:{self.postgres_port}/{quote(self.postgres_db, safe='')}")
        return self

    @property
    def sellers_json_source_list(self) -> list[str]:
        """Entries are `url` or `adsystem.com|url` (when the file is hosted off the ad-system domain)."""
        return [s.strip() for s in self.sellers_json_sources.split(",") if s.strip()]

    @staticmethod
    def split_sellers_source(entry: str) -> tuple[str | None, str]:
        if "|" in entry:
            sys_, url = entry.split("|", 1)
            return sys_.strip().lower(), url.strip()
        return None, entry.strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
