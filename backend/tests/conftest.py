"""Test configuration. DB tests run against a dedicated Postgres database (TEST_DATABASE_URL)."""
import os
import shutil
import tempfile

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://purify:purify@localhost:5432/purify_test")
os.environ["DATABASE_URL"] = TEST_DB
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ppi-test-"))
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("PER_HOST_MIN_INTERVAL_SECONDS", "0")
os.environ.setdefault("PLAYWRIGHT_SETTLE_MS", "1500")
_chrome = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
if os.path.exists(_chrome):
    os.environ.setdefault("CHROMIUM_EXECUTABLE", _chrome)

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


def _db_available() -> bool:
    try:
        eng = create_engine(TEST_DB)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def migrated_db():
    if not _db_available():
        pytest.skip("test database not available")
    from alembic import command
    from alembic.config import Config

    from app.core.config import get_settings
    from app.core.db import reset_engine

    get_settings.cache_clear()
    eng = create_engine(TEST_DB)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    eng.dispose()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    reset_engine()
    yield TEST_DB
    reset_engine()


@pytest.fixture
def clean_db(migrated_db):
    from app.core.db import get_engine

    with get_engine().begin() as c:
        tables = c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")).scalars().all()
        c.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
    yield migrated_db


@pytest.fixture
def chromium_available():
    if not os.environ.get("CHROMIUM_EXECUTABLE") and not shutil.which("chromium"):
        pytest.skip("no chromium available")
