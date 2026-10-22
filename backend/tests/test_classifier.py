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


# ---- regressions from the 116-site live run (2026-10-22) -----------------------------------------
def _page(title, headlines, extra="", nav="", schema='{"@type":"NewsMediaOrganization","name":"X"}', path="/news"):
    links = "".join(f'<article><a href="{path}/{i}-{h.lower().replace(" ", "-")[:60]}">{h}</a></article>' for i, h in enumerate(headlines))
    return (f'<html lang="en"><head><title>{title}</title><script type="application/ld+json">{schema}</script></head>'
            f'<body><nav>{nav}</nav>{links}{extra}</body></html>')


BROAD_NAV = "".join(f'<a href="/{x}">{x}</a>' for x in ["News", "Sport", "Culture", "Lifestyle", "Food", "Travel", "Money", "Tech", "Games", "Film"])


@pytest.mark.parametrize("host,title,heads,expected", [
    ("ign.com", "IGN: Video Game News, Reviews and Walkthroughs",
     ["Zelda remake gets PS5 and Xbox release date", "Best RPG games of 2026 ranked", "Elden Ring DLC boss fight guide",
      "Nintendo Switch 2 sales top 20 million", "Call of Duty multiplayer patch notes", "Minecraft update adds new biome",
      "Marvel movie trailer breakdown"], "GAMING_PUBLISHER"),
    ("espn.com", "ESPN - Serving Sports Fans. Anytime. Anywhere.",
     ["Chiefs quarterback ruled out of playoff game", "NBA trade deadline winners", "Premier League title race heats up",
      "Transfer news: striker joins rival club", "UFC champion defends belt", "Golf: leader after round two"], "SPORTS_PUBLISHER"),
    ("variety.com", "Variety - Entertainment News, Film Reviews, Awards",
     ["Box office: new Marvel movie tops weekend", "Netflix renews drama for third season", "Oscar race: actress buzz grows",
      "Singer announces world tour and album", "HBO series finale draws record audience", "Hollywood studio cuts film slate"],
     "ENTERTAINMENT_PUBLISHER"),
    ("theguardian.com", "News, sport and opinion from the Guardian's global edition",
     ["Prime minister faces vote on budget", "Ukraine war: Russia launches new attack", "Court rules on election law challenge",
      "Police arrest protest leaders", "Premier League: derby ends in draw", "EU leaders meet on migration crisis",
      "Recipe: autumn salad"], "NEWS_PUBLISHER"),
    ("delish.com", "Delish: Recipes, Cooking Tips and Food News",
     ["Easy chicken dinner recipe", "Best chocolate cake you will ever bake", "Five minute salad for busy weeknights",
      "Our favourite dessert recipes this fall", "How to cook perfect rice", "Grocery prices rise again, says report"], "LIFESTYLE_PUBLISHER"),
])
def test_niche_from_headlines(host, title, heads, expected):
    res = classify(host, [extract(_page(title, heads, nav=BROAD_NAV), f"https://www.{host}/")], ads_txt_records=50)
    assert res.primary_category == expected


def test_corporate_insights_site_without_ads_is_corporate():
    """accenture/deloitte-style: article schema + many insight articles, but corporate nav and no ad evidence."""
    nav = "".join(f'<a href="/{x.lower().replace(" ", "-")}">{x}</a>' for x in
                  ["Insights", "Industries", "Services", "Careers", "Investors", "About us", "Case studies", "Newsroom", "Contact us"])
    html = _page("Accenture | Let there be change", [f"How AI transforms the enterprise supply chain part {i}" for i in range(20)],
                 nav=nav, schema='{"@type":"Article"}', path="/insights")
    res = classify("accenture.com", [extract(html, "https://www.accenture.com/")], ads_txt_records=0)
    assert res.primary_category == "CORPORATE" and res.is_publisher is False
    # the same page WITH ad sellers in ads.txt stays a publisher
    res2 = classify("accenture.com", [extract(html, "https://www.accenture.com/")], ads_txt_records=40)
    assert res2.is_publisher is True


def test_retailer_with_cart_and_products_is_ecommerce():
    links = "".join(f'<a href="/p/sneaker-model-{i}">Sneaker {i} 89,95 €</a>' for i in range(15))
    html = f'<html lang="de"><head><title>Zalando: Mode & Schuhe online kaufen</title></head><body><nav><a href="/cart">Warenkorb</a>' \
           f'<a href="/damen">Damen</a></nav>{links}' + "".join(f'<a href="/magazin/{i}-style-trends-for-the-autumn-season">Style trends for the autumn season {i}</a>' for i in range(10)) + '</body></html>'
    res = classify("zalando.de", [extract(html, "https://www.zalando.de/")], ads_txt_records=0)
    assert res.primary_category == "ECOMMERCE"


def test_bank_is_not_a_finance_publisher():
    html = _page("HSBC UK - Personal & Online Banking", [f"Five ways to save money this winter tip {i}" for i in range(15)],
                 extra="<p>Online banking. Log on. Current account, savings account, credit cards, mortgages, personal loan.</p>",
                 nav='<a href="/accounts">Current account</a><a href="/mortgages">Mortgages</a><a href="/loans">Loans</a>',
                 schema='{"@type":"Article"}', path="/help")
    res = classify("hsbc.co.uk", [extract(html, "https://www.hsbc.co.uk/")], ads_txt_records=0)
    assert res.is_publisher is False


def test_government_registrable_root_host():
    res = classify("gov.bg", [extract(_page("Портал за правителство", ["Министерски съвет прие решение"] * 8), "https://gov.bg/")])
    assert res.primary_category == "GOVERNMENT"
