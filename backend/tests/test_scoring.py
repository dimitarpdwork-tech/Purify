from app.adtech.detector import ACTIVE, DECLARED, INCONCLUSIVE, NOT_OBSERVED, POSSIBLE
from app.scoring.opportunity import EvidenceBundle, assess
from app.scoring.score import ScoreInput, compute, popularity_score


def bundle(vendors, rendered=2, **kw):
    v = {k: {"status": s, "confidence": 0.8, "category": c, "name": k, "detail": d} for k, (s, c, d) in vendors.items()}
    base = dict(is_publisher=True, category="NEWS_PUBLISHER", classification_confidence=0.9, vendors=v, rendered_pages_ok=rendered,
                static_pages_ok=3, adtech_scanned=True, ads_txt_status="FOUND", ads_txt_record_count=10, ads_txt_systems=["google.com"])
    base.update(kw)
    return EvidenceBundle(**base)


KEYS_ABSENT = {"google_adsense": (NOT_OBSERVED, "adsense", {}), "prebid": (NOT_OBSERVED, "header_bidding", {}),
               "amazon_aps": (NOT_OBSERVED, "header_bidding", {})}


def test_gam_without_hb_is_B():
    b = bundle({"google_gam": (ACTIVE, "ad_server", {"network_codes": ["123"], "mcm_child_networks": []}), **KEYS_ABSENT})
    types = {o.type for o in assess(b)}
    assert "B" in types and "A" not in types


def test_B_requires_rendered_scan():
    b = bundle({"google_gam": (ACTIVE, "ad_server", {}), **KEYS_ABSENT}, rendered=0)
    assert "B" not in {o.type for o in assess(b)}


def test_adsense_only_is_A():
    b = bundle({"google_gam": (NOT_OBSERVED, "ad_server", {}), "google_adsense": (ACTIVE, "adsense", {}),
                "prebid": (NOT_OBSERVED, "header_bidding", {}), "amazon_aps": (NOT_OBSERVED, "header_bidding", {})})
    ops = {o.type: o for o in assess(b)}
    assert "A" in ops and ops["A"].confidence == 0.75


def test_limited_bidders_is_C_and_partner_is_E():
    b = bundle({"google_gam": (ACTIVE, "ad_server", {}), "prebid": (ACTIVE, "header_bidding", {"configured_bidders": ["ix", "rubicon"]}),
                "ezoic": (ACTIVE, "monetization_partner", {}), "google_adsense": (NOT_OBSERVED, "adsense", {}),
                "amazon_aps": (NOT_OBSERVED, "header_bidding", {})})
    assert {"C", "E"} <= {o.type for o in assess(b)}


def test_no_ads_popular_is_F_not_monetizable_claim():
    b = bundle({"google_gam": (NOT_OBSERVED, "ad_server", {}), **KEYS_ABSENT}, ads_txt_record_count=0, popularity_points=25)
    ops = assess(b)
    assert [o.type for o in ops] == ["F"]
    assert "not treat as immediately monetizable" in ops[0].approach.lower()


def test_declared_only_does_not_count_as_active_demand():
    b = bundle({"google_gam": (ACTIVE, "ad_server", {}), **KEYS_ABSENT, "pubmatic": (DECLARED, "ssp", {})})
    assert "B" in {o.type for o in assess(b)}  # ads.txt listing does not imply header bidding


def test_inconclusive_scan_is_G():
    b = bundle({"google_gam": (INCONCLUSIVE, "ad_server", {})}, rendered=0, static_pages_ok=0, adtech_scanned=True)
    assert [o.type for o in assess(b)] == ["G"]


def test_non_publisher_gets_no_opportunity():
    assert assess(bundle({}, is_publisher=False)) == []


def _input(b, **kw):
    base = dict(excluded=False, exclusion_reason=None, category="NEWS_PUBLISHER", secondary=[], is_publisher=True,
                classification_confidence=0.9, crux_buckets={"global": 10000, "GB": 1000}, tranco_best=5000, bundle=b,
                opportunities=assess(b))
    base.update(kw)
    return ScoreInput(**base)


def test_score_components_and_bounds():
    b = bundle({"google_gam": (ACTIVE, "ad_server", {}), **KEYS_ABSENT},
               inventory={"types": {"in_content": 2, "sidebar": 1}, "placements_per_page": 3})
    r = compute(_input(b, organization="Herald Ltd", business_links={"advertise": "https://x/advertise"}))
    assert r.popularity == 25 and r.audience_geo == 15
    assert 0 <= r.total <= 100
    assert r.queue == "HIGH_POTENTIAL_VERIFY_TRAFFIC"
    assert r.queue != "VERIFIED_HIGH_VALUE"  # never automatic without verified traffic


def test_missing_data_scores_zero_and_is_listed():
    b = bundle({"google_gam": (ACTIVE, "ad_server", {}), **KEYS_ABSENT})
    r = compute(_input(b, crux_buckets={}, tranco_best=None))
    assert r.popularity == 0 and r.audience_geo == 0
    assert "popularity (CrUX/Tranco)" in r.missing_critical
    assert r.queue != "HIGH_POTENTIAL_VERIFY_TRAFFIC"


def test_language_tld_is_not_audience():
    r = popularity_score({"global": 1000}, None)
    assert r[0] == 30


def test_excluded_categories():
    b = bundle({})
    assert compute(_input(b, category="ECOMMERCE", is_publisher=False, opportunities=[])).queue == "EXCLUDED"
    assert compute(_input(b, category="ECOMMERCE", is_publisher=False, secondary=["GENERAL_CONTENT_PUBLISHER"], opportunities=[])).queue != "EXCLUDED"
    assert compute(_input(b, excluded=True, exclusion_reason="manual")).queue == "EXCLUDED"


def test_possible_only_evidence_never_triggers_B():
    b = bundle({"google_gam": (POSSIBLE, "ad_server", {}), **KEYS_ABSENT})
    assert "B" not in {o.type for o in assess(b)}
