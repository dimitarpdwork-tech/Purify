"""End-to-end pipeline test on LOCAL FIXTURE SITES (tests/fixtures/vhosts served by vhost_server.py).

Requires: Postgres test DB, Chromium, /etc/hosts entries mapping *-fixture.com to 127.0.0.1 and
the fixture server on port 80 (see tests/README.md). Skips otherwise. This validates wiring and
logic only - it is not evidence about any real website.
"""
import os
import socket

import pytest
from sqlalchemy import select

FIXTURE_HOSTS = ["dailyherald-fixture.com", "gamezone-fixture.com", "acmeshoes-fixture.com", "quickrecipes-fixture.com"]


def _fixture_server_up() -> bool:
    try:
        if socket.gethostbyname("dailyherald-fixture.com") != "127.0.0.1":
            return False
        with socket.create_connection(("127.0.0.1", 80), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture
def fixture_env(clean_db, chromium_available, monkeypatch):
    if not _fixture_server_up():
        pytest.skip("fixture vhost server not running / hosts not mapped")
    monkeypatch.setenv("ALLOW_PRIVATE_NETWORK_FETCH", "true")
    monkeypatch.setenv("NO_PROXY", ",".join(FIXTURE_HOSTS + ["www." + h for h in FIXTURE_HOSTS] + ["127.0.0.1", "localhost"]))
    monkeypatch.setenv("no_proxy", os.environ["NO_PROXY"])
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _drain():
    from app.pipeline.claims import STAGES, claim
    from app.pipeline.stages import STAGE_RUNNERS

    for _ in range(12):
        progressed = False
        for st in STAGES:
            ids = claim(st, 50)
            if ids:
                STAGE_RUNNERS[st](ids)
                progressed = True
        if not progressed:
            return


def test_discovery_to_opportunity_profile(fixture_env):
    from app.core.db import session_scope
    from app.models import (
        AdsTxtFile, DetectedTechnology, OpportunityAssessment, Score, StageStatus, Website, WebsiteClassification,
    )
    from app.services.normalize import normalize
    from app.services.registry import Discovered, register

    with session_scope() as s:
        register(s, [Discovered(norm=normalize(h), source_type="manual", source_ref="e2e", priority=50) for h in FIXTURE_HOSTS])
    _drain()

    with session_scope() as s:
        stages = {(w, st): status for w, st, status in s.execute(select(StageStatus.website_id, StageStatus.stage, StageStatus.status))}
        hosts = dict(s.execute(select(Website.host, Website.id)).all())
        herald, game, shop, recipes = (hosts[h] for h in FIXTURE_HOSTS)

        # every stage reached a terminal state
        assert all(v in ("DONE", "SKIPPED", "FAILED") for v in stages.values()), stages
        assert not [k for k, v in stages.items() if v == "FAILED"], stages

        # classification
        cls = {w: c for w, c in s.execute(select(WebsiteClassification.website_id, WebsiteClassification.primary_category)
                                          .where(WebsiteClassification.is_current.is_(True)))}
        assert cls[herald] == "NEWS_PUBLISHER"
        assert cls[game] == "GAMING_PUBLISHER"
        assert cls[shop] == "ECOMMERCE"
        assert cls[recipes] == "LIFESTYLE_PUBLISHER"
        assert stages[(shop, "classify")] == "SKIPPED"  # non-publisher does not get an ad-tech scan

        # ads.txt
        f = s.scalar(select(AdsTxtFile).where(AdsTxtFile.website_id == herald, AdsTxtFile.is_current.is_(True)))
        assert f.status == "FOUND" and f.record_count == 4 and f.variables["OWNERDOMAIN"] == ["dailyherald-fixture.com"]

        # ad-tech for the rendered fixture with GPT/Prebid stubs
        det = {d.vendor_key: d for d in s.scalars(select(DetectedTechnology).where(DetectedTechnology.website_id == game,
                                                                                    DetectedTechnology.is_current.is_(True)))}
        assert det["google_gam"].status == "DETECTED_ACTIVE_SIGNALS"
        assert det["prebid"].status == "DETECTED_ACTIVE_SIGNALS"
        assert det["index_exchange"].status == "DETECTED_ACTIVE_SIGNALS"
        assert det["appnexus" if "appnexus" in det else "xandr"].status in ("DETECTED_ACTIVE_SIGNALS",)
        assert det["google_gam"].detail["mcm_child_networks"] == ["7654321"]
        # herald: static GPT reference, but GPT never initialised in the page -> not 'active'
        dh = {d.vendor_key: d for d in s.scalars(select(DetectedTechnology).where(DetectedTechnology.website_id == herald,
                                                                                   DetectedTechnology.is_current.is_(True)))}
        assert dh["google_gam"].status == "POSSIBLE"
        assert dh["pubmatic"].status == "DECLARED_AUTHORIZATION_ONLY"

        # opportunities and scores exist with explanations; no traffic numbers anywhere
        opps = {o.opportunity_type for o in s.scalars(select(OpportunityAssessment).where(
            OpportunityAssessment.website_id == game, OpportunityAssessment.is_current.is_(True)))}
        assert "C" in opps and "E" in opps  # 3 client bidders; MCM child network
        recipe_opps = {o.opportunity_type for o in s.scalars(select(OpportunityAssessment).where(
            OpportunityAssessment.website_id == recipes, OpportunityAssessment.is_current.is_(True)))}
        assert "A" in recipe_opps
        sc = s.scalar(select(Score).where(Score.website_id == game, Score.is_current.is_(True)))
        assert sc.popularity == 0 and "popularity (CrUX/Tranco)" in sc.missing_critical
        assert sc.queue != "VERIFIED_HIGH_VALUE"
        shop_score = s.scalar(select(Score).where(Score.website_id == shop, Score.is_current.is_(True)))
        assert shop_score.queue == "EXCLUDED"

        w = s.get(Website, game)
        assert w.gam_status == "DETECTED_ACTIVE_SIGNALS" and w.monetization_type in ("GAM_HEADER_BIDDING", "MANAGED_PARTNER")
        assert "index_exchange" in (w.observed_partners or [])


def test_failed_rescan_keeps_previous_evidence(fixture_env, monkeypatch):
    """A later failed scan must not erase earlier conclusions."""
    from app.core.db import session_scope
    from app.models import DetectedTechnology, Website, WebsiteClassification
    from app.pipeline.claims import enqueue
    from app.services.normalize import normalize
    from app.services.registry import Discovered, register

    with session_scope() as s:
        register(s, [Discovered(norm=normalize("gamezone-fixture.com"), source_type="manual", source_ref="e2e", priority=50)])
    _drain()
    with session_scope() as s:
        wid = s.scalar(select(Website.id).where(Website.host == "gamezone-fixture.com"))
        before = s.scalar(select(WebsiteClassification.primary_category).where(WebsiteClassification.website_id == wid,
                                                                                 WebsiteClassification.is_current.is_(True)))
    # site "goes down": block private fetches again so every request is refused
    monkeypatch.setenv("ALLOW_PRIVATE_NETWORK_FETCH", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    with session_scope() as s:
        enqueue(s, wid, "classify")
        enqueue(s, wid, "adtech")
    _drain()
    with session_scope() as s:
        after = s.scalar(select(WebsiteClassification.primary_category).where(WebsiteClassification.website_id == wid,
                                                                                WebsiteClassification.is_current.is_(True)))
        gam = s.scalar(select(DetectedTechnology.status).where(DetectedTechnology.website_id == wid, DetectedTechnology.is_current.is_(True),
                                                               DetectedTechnology.vendor_key == "google_gam"))
    assert after == before == "GAMING_PUBLISHER"
    assert gam == "DETECTED_ACTIVE_SIGNALS"
    from app.models import OpportunityAssessment, Scan

    with session_scope() as s:
        failed = s.scalar(select(Scan.status).where(Scan.website_id == wid, Scan.kind == "rendered").order_by(Scan.id.desc()).limit(1))
        opps = {o for o in s.scalars(select(OpportunityAssessment.opportunity_type).where(
            OpportunityAssessment.website_id == wid, OpportunityAssessment.is_current.is_(True)))}
    assert failed == "FAILED"
    assert "G" not in opps and "C" in opps  # earlier successful evidence still drives the assessment
