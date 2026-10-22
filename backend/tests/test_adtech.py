from pathlib import Path

from app.adtech.detector import (
    ACTIVE, DECLARED, INCONCLUSIVE, NOT_OBSERVED, POSSIBLE, AdsTxtObservation, PageObservation, detect, summarize,
)
from app.adtech.registry import load_registry

FX = Path(__file__).parent / "fixtures" / "html"


def by_key(results):
    return {r.vendor_key: r for r in results}


def test_registry_loads_and_indexes():
    reg = load_registry()
    assert reg.vendor_for_ad_system("rubiconproject.com") == "magnite"
    assert reg.vendor_for_ad_system("www.google.com") == "google_ads_txt"
    assert reg.vendor_for_bidder("IX") == "index_exchange"
    assert len(reg.vendors) > 60


def test_static_scan_only_yields_possible_not_active():
    html = (FX / "news_home.html").read_text()
    r = by_key(detect([PageObservation(url="https://x.com/", html=html)]))
    assert r["google_gam"].status == POSSIBLE
    assert r["prebid"].status == POSSIBLE
    # APS absent in static HTML -> NOT_OBSERVED but low confidence (static only)
    assert r["amazon_aps"].status == NOT_OBSERVED
    assert r["amazon_aps"].detail["scan_depth"] == "static_only"
    assert r["google_gam"].detail["network_codes"] == ["1234567"]


def test_rendered_signals_are_active_and_bidders_map_to_vendors():
    page = PageObservation(
        url="https://x.com/", rendered=True,
        network_urls=["https://securepubads.g.doubleclick.net/gampad/ads?iu=/1234,5555/x", "https://htlb.casalemedia.com/openrtb/pbjs?s=1"],
        globals_present={"googletag.pubadsReady": True},
        prebid=[{"global": "pbjs", "version": "v8.39.0", "configured_bidders": ["ix", "rubicon", "someboutique"], "requested_bidders": ["ix"], "responding_bidders": []}],
        gpt={"slots": [{"path": "/1234,5555/site/top", "sizes": ["728x90"], "div": "d"}]},
    )
    r = by_key(detect([page]))
    assert r["google_gam"].status == ACTIVE
    assert r["prebid"].status == ACTIVE
    assert r["index_exchange"].status == ACTIVE
    assert r["magnite"].status == ACTIVE  # configured bidder
    assert r["google_gam"].detail["mcm_child_networks"] == ["5555"]
    assert "someboutique" in r["prebid"].detail["unmapped_bidders"]
    assert r["google_adsense"].status == NOT_OBSERVED and r["google_adsense"].detail["scan_depth"] == "rendered"
    s = summarize(list(r.values()))
    assert s["gam_mcm"] is True and "ix" in s["prebid_bidders"]


def test_ads_txt_only_is_declared_authorization():
    ads = AdsTxtObservation("FOUND", [
        {"ad_system_domain": "pubmatic.com", "seller_account_id": "1", "relationship": "DIRECT"},
        {"ad_system_domain": "openx.com", "seller_account_id": "2", "relationship": "RESELLER"},
    ])
    r = by_key(detect([PageObservation(url="https://x.com/", html="<html></html>")], ads))
    assert r["pubmatic"].status == DECLARED
    assert r["openx"].status == DECLARED
    assert r["pubmatic"].detail["ads_txt"]["direct_accounts"] == ["1"]


def test_failed_scan_is_inconclusive_not_absent():
    r = by_key(detect([PageObservation(url="https://x.com/", ok=False, blocked_reason="robots.txt disallows")]))
    for k in ("google_gam", "google_adsense", "prebid", "amazon_aps"):
        assert r[k].status == INCONCLUSIVE


def test_adsense_static_detection():
    r = by_key(detect([PageObservation(url="https://q.com/", html=(FX / "adsense_blog.html").read_text())]))
    assert r["google_adsense"].status == POSSIBLE
    assert r["google_adsense"].detail["publisher_ids"] == ["ca-pub-1234567890123456"]
