"""Classifier tests on synthetic HTML fixtures (tests/fixtures/html). These are fixtures, not
production evidence; live behaviour is validated by scripts/live_validate.py."""
from pathlib import Path

import pytest

from app.classify.features import country_signals, extract
from app.classify.rules import PUBLISHER_CATEGORIES, classify

FX = Path(__file__).parent / "fixtures" / "html"


def feats(name: str, url: str):
    return extract((FX / name).read_text(), url)


def test_news_publisher_with_article_sample():
    home = feats("news_home.html", "https://www.dailyherald.co.uk/")
    art = feats("news_article.html", "https://www.dailyherald.co.uk/2026/10/1/minister-announces-new-budget-plan-1")
    res = classify("dailyherald.co.uk", [home, art])
    assert res.primary_category == "NEWS_PUBLISHER"
    assert res.is_publisher is True
    assert res.confidence >= 0.8
    signals = {e["signal"] for e in res.supporting}
    assert "sampled content page is a dated article" in signals
    assert "GB" in country_signals([home], "dailyherald.co.uk")


def test_ecommerce_is_not_publisher():
    res = classify("acmeshoes.com", [feats("shop_home.html", "https://acmeshoes.com/")])
    assert res.primary_category == "ECOMMERCE"
    assert res.is_publisher is False


def test_saas_on_wordpress_is_saas():
    res = classify("flowboard.io", [feats("saas_home.html", "https://flowboard.io/")])
    assert res.primary_category == "SAAS"
    assert res.is_publisher is False


def test_wordpress_alone_does_not_make_a_publisher():
    res = classify("smithco.com", [feats("wordpress_brochure.html", "https://smithco.com/")])
    assert res.primary_category not in PUBLISHER_CATEGORIES
    assert res.is_publisher in (False, None)


def test_parked_domain():
    res = classify("coolname.com", [feats("parked.html", "https://coolname.com/")])
    assert res.primary_category == "PARKED_DOMAIN"


def test_forum_community():
    res = classify("gearheads.net", [feats("forum_home.html", "https://gearheads.net/")])
    assert res.primary_category == "FORUM_COMMUNITY"
    assert res.is_publisher is True


def test_government_suffix():
    res = classify("tax.service.gov.uk", [feats("wordpress_brochure.html", "https://tax.service.gov.uk/")])
    assert res.primary_category == "GOVERNMENT"


def test_challenge_page_is_unknown_not_absence():
    res = classify("blocked.com", [feats("challenge.html", "https://blocked.com/")])
    assert res.primary_category == "UNKNOWN"
    assert res.is_publisher is None
    assert res.confidence == 0.0


def test_fetch_failure_is_unknown():
    res = classify("down.com", [], fetch_ok=False, blocked_reason="timeout")
    assert res.primary_category == "UNKNOWN"


@pytest.mark.parametrize("name,expected", [("adsense_blog.html", "LIFESTYLE_PUBLISHER")])
def test_recipe_blog_topic(name, expected):
    res = classify("quickrecipes.com", [feats(name, "https://quickrecipes.com/")])
    assert res.primary_category == expected


def test_jsonld_list_types_and_odd_values_do_not_crash():
    """Regression (found live on bbc.com): schema.org @type given as a list, names as lists/objects."""
    html = """<html lang="en-GB"><head><title>BBC - Home</title>
    <script type="application/ld+json">{"@context":"https://schema.org","@graph":[
      {"@type":["Organization","NewsMediaOrganization"],"name":["BBC"]},
      {"@type":["WebPage"],"name":{"@value":"Home"}},
      {"@type":[{"weird":1},"Thing"],"name":"x"},
      {"@type":"https://schema.org/NewsArticle","headline":"h"}]}</script></head>
    <body><nav><a href="/news">News</a><a href="/sport">Sport</a></nav></body></html>"""
    f = extract(html, "https://www.bbc.com/")
    assert f["org_names"] == ["BBC"]
    assert "NewsMediaOrganization" in f["schema_types"]


def test_extract_safe_never_raises():
    from app.classify.features import extract_safe

    out = extract_safe("<html><body>" + "<a href='http://[bad'>x</a>" * 3 + "</body></html>", "https://example.com/")
    assert isinstance(out, dict)


def test_broad_news_site_with_lifestyle_sections_is_news():
    """Regression (live: theguardian.com was labelled LIFESTYLE). Many lifestyle nav words + news schema."""
    html = """<html lang="en-GB"><head><title>News, sport and opinion from the Guardian's global edition</title>
    <script type="application/ld+json">{"@type":"NewsMediaOrganization","name":"The Guardian"}</script></head><body>
    <nav><a href="/world">World</a><a href="/sport">Sport</a><a href="/culture">Culture</a><a href="/film">Film</a><a href="/music">Music</a>
    <a href="/lifestyle">Lifestyle</a><a href="/food">Food</a><a href="/travel">Travel</a><a href="/fashion">Fashion</a><a href="/health">Health</a>
    <a href="/money">Money</a><a href="/technology">Technology</a><a href="/games">Games</a></nav>""" + \
        "".join(f'<article><a href="/world/2026/oct/{i}/story-about-many-things-{i}">s</a></article>' for i in range(1, 30)) + "</body></html>"
    res = classify("theguardian.com", [extract(html, "https://www.theguardian.com/europe")])
    assert res.primary_category == "NEWS_PUBLISHER"
