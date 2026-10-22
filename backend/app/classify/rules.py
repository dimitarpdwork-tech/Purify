"""Deterministic publisher classifier.

Scores competing hypotheses (publisher, ecommerce, SaaS, corporate, forum, tool, government,
parked) from page features and records supporting and contradictory evidence for each signal.
Generic CMS fingerprints (e.g. WordPress) carry NO publisher weight on their own.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from app.classify.features import (
    ARTICLE_SCHEMA, COMMERCE_SCHEMA, FORUM_SCHEMA, GOV_SCHEMA, NEWS_SCHEMA, SAAS_SCHEMA, TOPIC_KEYWORDS,
)

ENGINE_VERSION = "classify-1.0"
PUBLISHER_CATEGORIES = {
    "NEWS_PUBLISHER", "ENTERTAINMENT_PUBLISHER", "SPORTS_PUBLISHER", "GAMING_PUBLISHER", "TECHNOLOGY_PUBLISHER",
    "FINANCE_PUBLISHER", "LIFESTYLE_PUBLISHER", "EDUCATIONAL_PUBLISHER", "FORUM_COMMUNITY", "CONTENT_TOOL",
    "GENERAL_CONTENT_PUBLISHER",
}
ALL_CATEGORIES = sorted(PUBLISHER_CATEGORIES | {"ECOMMERCE", "CORPORATE", "SAAS", "MARKETPLACE", "GOVERNMENT", "PARKED_DOMAIN", "OTHER", "UNKNOWN"})
GOV_SUFFIXES = (".gov", ".mil", ".gov.uk", ".gouv.fr", ".gob.es", ".gob.mx", ".gov.au", ".gc.ca", ".bund.de", ".government.bg",
                ".gov.bg", ".gov.in", ".gov.br", ".go.jp", ".go.kr", ".gov.cn", ".europa.eu", ".gov.pl", ".gov.it")


@dataclass
class ClassificationResult:
    primary_category: str
    secondary_categories: list[str]
    is_publisher: bool | None
    confidence: float
    supporting: list[dict[str, Any]] = field(default_factory=list)
    contradictory: list[dict[str, Any]] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    pages_inspected: list[str] = field(default_factory=list)
    engine_version: str = ENGINE_VERSION


class _Acc:
    def __init__(self) -> None:
        self.scores: dict[str, float] = {k: 0.0 for k in ("publisher", "ecommerce", "saas", "corporate", "forum", "tool", "government", "parked")}
        self.ev: list[dict[str, Any]] = []

    def add(self, hyp: str, w: float, signal: str, value: Any = None) -> None:
        self.scores[hyp] += w
        self.ev.append({"hypothesis": hyp, "weight": w, "signal": signal, "value": value})


def classify(host: str, pages: list[dict[str, Any]], fetch_ok: bool = True, blocked_reason: str | None = None,
             ads_txt_records: int | None = None) -> ClassificationResult:
    """`ads_txt_records`: number of ads.txt records (None = unknown / not fetched)."""
    good = [p for p in pages if not p.get("empty") and not p.get("unparseable")]
    urls = [p.get("url") for p in pages if p.get("url")]
    if not fetch_ok or not good:
        return ClassificationResult("UNKNOWN", [], None, 0.0,
                                    contradictory=[{"signal": "no usable page content", "value": blocked_reason}], pages_inspected=urls)
    if all(p.get("challenge_page") for p in good):
        return ClassificationResult("UNKNOWN", [], None, 0.0,
                                    contradictory=[{"signal": "anti-bot / challenge page served; not bypassed"}], pages_inspected=urls)

    home = good[0]
    others = good[1:]
    a = _Acc()
    types = set(home.get("schema_types", []))
    other_types: set[str] = set()
    for p in others:
        other_types |= set(p.get("schema_types", []))
    all_types = types | other_types
    tech = home.get("tech", {})

    # ---------------- parked / government
    if home.get("parked_phrases"):
        a.add("parked", 3 + len(home["parked_phrases"]), "parking/for-sale phrases", home["parked_phrases"])
        if home.get("word_count", 0) < 300:
            a.add("parked", 2, "very little page text", home.get("word_count"))
    if host.endswith(GOV_SUFFIXES) or ("." + host) in GOV_SUFFIXES:
        a.add("government", 8, "government domain suffix", host)
    if types & GOV_SCHEMA:
        a.add("government", 4, "GovernmentOrganization schema", sorted(types & GOV_SCHEMA))
    if home.get("gov_phrases"):
        a.add("government", 1.5, "government wording", home["gov_phrases"])

    # ---------------- publisher
    if all_types & NEWS_SCHEMA:
        a.add("publisher", 4, "NewsArticle / NewsMediaOrganization schema", sorted(all_types & NEWS_SCHEMA))
    elif all_types & ARTICLE_SCHEMA:
        a.add("publisher", 3, "Article / BlogPosting schema", sorted(all_types & ARTICLE_SCHEMA))
    if home.get("og_type") == "article" or any(p.get("og_type") == "article" for p in others):
        a.add("publisher", 1, "og:type=article on sampled page")
    if home.get("feed_links"):
        a.add("publisher", 2, "RSS/Atom feed advertised", home["feed_links"][:2])
    n_art = home.get("article_link_count", 0)
    if n_art >= 40:
        a.add("publisher", 4, "many article-style internal links", n_art)
    elif n_art >= 15:
        a.add("publisher", 3, "article-style internal links", n_art)
    elif n_art >= 6:
        a.add("publisher", 1, "some article-style internal links", n_art)
    if home.get("dated_link_count", 0) >= 5:
        a.add("publisher", 2, "date-stamped article URLs", home["dated_link_count"])
    if home.get("time_elements", 0) >= 5:
        a.add("publisher", 1, "<time> elements on homepage", home["time_elements"])
    if home.get("article_elements", 0) >= 5:
        a.add("publisher", 1, "<article> elements on homepage", home["article_elements"])
    if home.get("byline_elements", 0) >= 3 or home.get("has_author_meta"):
        a.add("publisher", 1, "author / byline markup")
    for p in others:
        if (set(p.get("schema_types", [])) & ARTICLE_SCHEMA) or p.get("has_published_time"):
            a.add("publisher", 3, "sampled content page is a dated article", p.get("url"))
            break
    deep = [p for p in others if p.get("word_count", 0) >= 400]
    if deep:
        a.add("publisher", 1, "sampled content pages have substantial text", [p.get("word_count") for p in deep])
    ad_cats = {k for k in tech if k in ("ad_server", "adsense", "header_bidding", "monetization_partner", "ssp", "native")}
    if ad_cats:
        a.add("publisher", 2, "advertising technology referenced in page", sorted(ad_cats))
    if ads_txt_records:
        a.add("publisher", 3, "ads.txt authorises ad sellers", ads_txt_records)
    has_ad_evidence = bool(ad_cats) or bool(ads_txt_records)

    # ---------------- forum
    if tech.get("forum_software"):
        a.add("forum", 5, "forum software fingerprint", tech["forum_software"])
    if all_types & FORUM_SCHEMA:
        a.add("forum", 4, "DiscussionForumPosting / QAPage schema", sorted(all_types & FORUM_SCHEMA))
    if len(home.get("forum_phrases", [])) >= 2:
        a.add("forum", 2, "forum wording in title/navigation", home["forum_phrases"])

    # ---------------- tool
    if home.get("tool_phrases"):
        a.add("tool", 3 + len(home["tool_phrases"]), "tool keywords in title/description", home["tool_phrases"])

    # ---------------- commerce
    if types & COMMERCE_SCHEMA:
        a.add("ecommerce", 4, "Product/Offer schema", sorted(types & COMMERCE_SCHEMA))
    if tech.get("ecommerce_platform"):
        a.add("ecommerce", 3, "e-commerce platform fingerprint", tech["ecommerce_platform"])
    if len(home.get("ecom_phrases", [])) >= 2:
        a.add("ecommerce", 3, "shopping cart / checkout wording", home["ecom_phrases"])
    elif home.get("ecom_phrases"):
        a.add("ecommerce", 1, "shopping wording", home["ecom_phrases"])
    if home.get("price_mentions", 0) >= 10:
        a.add("ecommerce", 2, "many price mentions", home["price_mentions"])
    if home.get("cart_links"):
        a.add("ecommerce", 2, "links to a shopping cart / basket", home["cart_links"])
    if home.get("product_link_count", 0) >= 8:
        a.add("ecommerce", 3, "many product page links", home["product_link_count"])
    if len(home.get("bank_phrases", [])) >= 3:
        a.add("corporate", 5, "banking products (accounts, loans, cards, online banking)", home["bank_phrases"][:6])

    # ---------------- SaaS
    if types & SAAS_SCHEMA:
        a.add("saas", 3, "SoftwareApplication schema", sorted(types & SAAS_SCHEMA))
    sp = set(home.get("saas_phrases", []))
    if len(sp & {"free trial", "start free", "request a demo", "book a demo", "pricing", "for teams", "enterprise plan", "api docs"}) >= 2:
        a.add("saas", 4, "SaaS calls to action (pricing/trial/demo)", sorted(sp))
    elif sp & {"free trial", "request a demo", "book a demo", "pricing"}:
        a.add("saas", 1.5, "pricing/trial/demo wording", sorted(sp))
    if home.get("password_inputs", 0) and home.get("word_count", 0) < 400:
        a.add("saas", 2, "login form on a thin homepage", home.get("password_inputs"))

    # ---------------- corporate
    if len(home.get("corp_phrases", [])) >= 2:
        a.add("corporate", 2 + 0.5 * len(home["corp_phrases"]), "corporate navigation (careers/investors/solutions)", home["corp_phrases"])
    if n_art < 6 and not home.get("feed_links") and home.get("word_count", 0) < 1500:
        a.add("corporate", 1, "few content links and no feed")

    # ---------------- generic CMS is NOT evidence
    supporting_cms = tech.get("cms", [])

    s = a.scores
    # Decide
    ranking = sorted(s.items(), key=lambda kv: kv[1], reverse=True)
    top, top_score = ranking[0]
    second, second_score = ranking[1]
    # Corporate blogs, retailers' editorial pages and SaaS "resources" sections produce article signals too.
    # Without any advertising evidence (no ad tech in the page, no ads.txt sellers), a credible business
    # hypothesis wins; the editorial side is kept as a secondary category.
    if top == "publisher" and not has_ad_evidence:
        biz = max(("corporate", "ecommerce", "saas"), key=lambda k: s[k])
        if s[biz] >= 4:
            a.add(biz, 0, "no advertising evidence (no ad tech, no ads.txt sellers) on a site with business signals")
            top, top_score = biz, s[biz]
            second, second_score = "publisher", s["publisher"]

    if top_score < 3:
        result_cat = "UNKNOWN" if home.get("word_count", 0) < 150 else "OTHER"
        res = ClassificationResult(result_cat, [], None, 0.25, scores=s, pages_inspected=urls)
        res.supporting = [e for e in a.ev]
        res.contradictory = [{"signal": "insufficient decisive signals", "value": round(top_score, 2)}]
        if supporting_cms:
            res.contradictory.append({"signal": "CMS fingerprint alone does not indicate a publisher", "value": supporting_cms})
        return res

    hyp_to_cat = {
        "parked": "PARKED_DOMAIN", "government": "GOVERNMENT", "ecommerce": "ECOMMERCE", "saas": "SAAS",
        "corporate": "CORPORATE", "forum": "FORUM_COMMUNITY", "tool": "CONTENT_TOOL",
    }
    secondary: list[str] = []
    # Mixed businesses: a strong editorial operation inside a commercial site is kept as a secondary publisher signal.
    if top in ("ecommerce", "saas", "corporate") and s["publisher"] >= 7:
        secondary.append("GENERAL_CONTENT_PUBLISHER")
    if top == "publisher":
        primary = _topic(home, others, all_types)
        if s["forum"] >= 4:
            secondary.append("FORUM_COMMUNITY")
        if s["ecommerce"] >= 5:
            secondary.append("ECOMMERCE")
    else:
        primary = hyp_to_cat[top]
        if top in ("forum", "tool"):
            topic = _topic(home, others, all_types, default=None)
            if topic and topic != primary:
                secondary.append(topic)
    if top == "ecommerce" and s["ecommerce"] >= 6 and "marketplace" in (home.get("title", "") + home.get("description", "")).lower():
        primary = "MARKETPLACE"

    margin = top_score - second_score
    conf = max(0.3, min(0.97, 0.45 + 0.05 * top_score + 0.04 * margin))
    if margin < 2:
        conf = min(conf, 0.55)

    supporting = [e for e in a.ev if e["hypothesis"] == top]
    contradictory = [e for e in a.ev if e["hypothesis"] != top and e["weight"] >= 1.5]
    if supporting_cms and top == "publisher":
        contradictory.append({"hypothesis": "note", "weight": 0, "signal": "CMS fingerprint ignored as evidence", "value": supporting_cms})
    is_pub = primary in PUBLISHER_CATEGORIES
    return ClassificationResult(primary, secondary, is_pub, round(conf, 3), supporting, contradictory, s, urls)


def _topic(home, others, all_types, default: str | None = "GENERAL_CONTENT_PUBLISHER") -> str | None:
    """Pick the publisher niche.

    1. Headlines (what the site actually publishes) decide when one niche clearly dominates.
    2. Otherwise the site's identity (title / domain words) decides when it names exactly one niche.
    3. Otherwise a site with news schema / news vocabulary is a general news publisher.
    Navigation menus are only a last resort: big news sites link to every section.
    """
    niche = ["GAMING_PUBLISHER", "SPORTS_PUBLISHER", "ENTERTAINMENT_PUBLISHER", "TECHNOLOGY_PUBLISHER", "FINANCE_PUBLISHER",
             "LIFESTYLE_PUBLISHER", "EDUCATIONAL_PUBLISHER"]
    head: dict[str, int] = dict(home.get("headline_topics") or {})
    n_head = int(home.get("headline_count") or 0)
    for p in others:
        for k, v in (p.get("headline_topics") or {}).items():
            head[k] = head.get(k, 0) + v
        n_head += int(p.get("headline_count") or 0)
    ident: dict[str, int] = dict(home.get("identity_topics") or {})
    if "Recipe" in all_types:
        head["LIFESTYLE_PUBLISHER"] = head.get("LIFESTYLE_PUBLISHER", 0) + 5
    if "VideoGame" in all_types:
        head["GAMING_PUBLISHER"] = head.get("GAMING_PUBLISHER", 0) + 5

    tagged = sum(head.values())
    ident_niche = [t for t in niche if ident.get(t)]
    if n_head >= 5 and tagged:
        share = {t: head.get(t, 0) / tagged for t in niche}
        best = max(niche, key=lambda t: (share[t], t in ident_niche))
        news_share = head.get("NEWS_PUBLISHER", 0) / tagged
        if share[best] >= 0.4 and share[best] > news_share:
            return best
    # Title names exactly one niche. If the title also says "news" ("Video Game News", "News, sport and
    # opinion"), the headlines must lean towards the niche rather than towards general news.
    if len(ident_niche) == 1:
        t = ident_niche[0]
        if ident.get("NEWS_PUBLISHER"):
            if head.get(t, 0) >= 2 and head.get(t, 0) > head.get("NEWS_PUBLISHER", 0):
                return t
        elif not (n_head >= 5 and tagged) or head.get(t, 0) / max(tagged, 1) >= 0.15:
            return t
    if all_types & NEWS_SCHEMA or ident.get("NEWS_PUBLISHER") or (tagged and head.get("NEWS_PUBLISHER", 0) / tagged >= 0.3):
        return "NEWS_PUBLISHER"
    # last resort: navigation / title keyword hits (capped so one section cannot dominate)
    hits = {k: min(v, 4) for k, v in (home.get("topic_hits") or {}).items()}
    if hits:
        best_k, best_v = max(hits.items(), key=lambda kv: kv[1])
        if best_v >= 2:
            return best_k
    return default


def as_record(res: ClassificationResult) -> dict[str, Any]:
    return {
        "primary_category": res.primary_category,
        "secondary_categories": res.secondary_categories,
        "is_publisher": res.is_publisher,
        "confidence": res.confidence,
        "supporting_evidence": res.supporting,
        "contradictory_evidence": res.contradictory,
        "features": {"scores": res.scores},
        "pages_inspected": res.pages_inspected,
        "engine_version": res.engine_version,
        "created_at": dt.datetime.now(dt.timezone.utc),
    }


assert set(TOPIC_KEYWORDS) <= set(ALL_CATEGORIES)
