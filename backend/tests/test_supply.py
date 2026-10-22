import json

from app.supply.adstxt import looks_like_html, parse
from app.supply.sellersjson import iter_sellers_from_file, iter_sellers_from_text

ADS = """﻿# ads.txt for example.com
OWNERDOMAIN=example.com
MANAGERDOMAIN=manager-network.com
CONTACT=adops@example.com
google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0
google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0
rubiconproject.com, 12345, RESELLER, 0bfd66d529a55807 # comment
https://www.pubmatic.com, 999, direct
appnexus.com, 777, RESELLER; ext=1
bad line without commas
openx.com, , DIRECT
indexexchange.com, 1, PARTNER
SUBDOMAIN=news.example.com
"""


def test_ads_txt_parse():
    p = parse(ADS)
    recs = [(r.ad_system_domain, r.seller_account_id, r.relationship) for r in p.records]
    assert ("google.com", "pub-1234567890123456", "DIRECT") in recs
    assert ("rubiconproject.com", "12345", "RESELLER") in recs
    assert ("pubmatic.com", "999", "DIRECT") in recs  # scheme/www stripped, case normalised
    assert ("appnexus.com", "777", "RESELLER") in recs
    assert p.duplicate_count == 1
    assert p.owner_domain == "example.com"
    assert p.manager_domains == ["manager-network.com"]
    assert p.subdomains == ["news.example.com"]
    reasons = {m["reason"] for m in p.malformed}
    assert "empty seller account id" in reasons
    assert any("invalid relationship" in r for r in reasons)
    assert "not a record or variable" in reasons


def test_html_served_as_ads_txt():
    assert looks_like_html("<!DOCTYPE html><html><body>404</body></html>")


def test_sellers_json_text_and_streaming(tmp_path):
    data = {"version": "1.0", "sellers": [
        {"seller_id": "pub-1", "name": "Herald Media", "domain": "dailyherald.co.uk", "seller_type": "PUBLISHER"},
        {"seller_id": "pub-2", "is_confidential": 1, "seller_type": "PUBLISHER"},
        {"seller_id": 3, "name": "Reseller Co", "domain": "reseller.com", "seller_type": "INTERMEDIARY"},
    ] * 2000}
    text = json.dumps(data)
    a = list(iter_sellers_from_text(text))
    f = tmp_path / "s.json"
    f.write_text(text)
    b = list(iter_sellers_from_file(str(f), chunk_size=4096))
    assert len(a) == len(b) == 6000
    assert b[0]["domain"] == "dailyherald.co.uk" and b[1]["is_confidential"] is True and b[2]["seller_id"] == "3"
