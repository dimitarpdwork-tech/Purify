"""Feature extraction from fetched HTML for publisher classification."""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any
from urllib.parse import urljoin, urlsplit

import lxml.html
from lxml import etree

from app.adtech.registry import load_registry

_DATE_PATH_RE = re.compile(r"/(19|20)\d{2}/(0?[1-9]|1[0-2])(/|-)|/(19|20)\d{2}-\d{2}-\d{2}|/(19|20)\d{6}/")
_PRICE_RE = re.compile(r"(?:[$€£¥₹]\s?\d{1,5}(?:[.,]\d{2})?|\d{1,5}(?:[.,]\d{2})\s?(?:€|EUR|USD|лв|zł|kr|Kč))")
_SLUG_RE = re.compile(r"/[a-z0-9À-ɏЀ-ӿ%]+(?:-[a-z0-9À-ɏЀ-ӿ%]+){3,}(?:/|\.html?|$)", re.I)
_ID_ARTICLE_RE = re.compile(r"/(news|article|articles|story|stories|post|posts|blog|a|n)/[^/?#]*\d{4,}", re.I)
_WS_RE = re.compile(r"\s+")

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "NEWS_PUBLISHER": ["news", "breaking", "politics", "world", "headlines", "latest", "noticias", "nachrichten", "actualités", "notizie",
                       "новини", "новости", "wiadomości", "haber", "notícias", "nieuws", "nyheter", "zprávy", "știri", "ειδήσεις", "election", "opinion"],
    "SPORTS_PUBLISHER": ["sport", "sports", "football", "soccer", "nba", "nfl", "cricket", "tennis", "fútbol", "futbol", "calcio", "fussball",
                         "спорт", "футбол", "transfer", "premier league", "f1", "formula 1", "basketball", "baseball", "hockey", "golf"],
    "GAMING_PUBLISHER": ["game", "games", "gaming", "esports", "playstation", "xbox", "nintendo", "steam", "pc gaming", "walkthrough", "игри", "minecraft", "fortnite"],
    "TECHNOLOGY_PUBLISHER": ["tech", "technology", "gadgets", "smartphone", "android", "iphone", "software", "ai", "reviews", "hardware", "cybersecurity", "технологии"],
    "FINANCE_PUBLISHER": ["finance", "markets", "stocks", "economy", "business", "investing", "crypto", "money", "personal finance", "бизнес", "финанси", "борса"],
    "ENTERTAINMENT_PUBLISHER": ["entertainment", "celebrity", "celebrities", "movies", "film", "tv", "music", "showbiz", "gossip", "anime", "streaming", "шоу", "звезди"],
    "LIFESTYLE_PUBLISHER": ["lifestyle", "recipes", "recipe", "food", "travel", "fashion", "beauty", "health", "parenting", "home", "garden", "diy",
                            "auto", "cars", "automotive", "wellness", "рецепти", "здраве", "мода", "кола", "автомобили"],
    "EDUCATIONAL_PUBLISHER": ["learn", "learning", "education", "course", "courses", "tutorial", "tutorials", "dictionary", "encyclopedia",
                              "how to", "guide", "lesson", "homework", "study", "exam", "wiki", "образование"],
}
TOOL_KEYWORDS = ["converter", "calculator", "translator", "generator", "checker", "downloader", "compress", "convert", "online tool",
                 "speed test", "weather", "timer", "editor", "lookup", "tracker", "калкулатор", "конвертор"]
ECOM_PHRASES = ["add to cart", "add to bag", "add to basket", "shopping cart", "checkout", "free shipping", "in stock", "buy now", "shop now",
                "добави в количката", "количка", "in den warenkorb", "ajouter au panier", "añadir al carrito"]
SAAS_PHRASES = ["sign up", "log in", "login", "free trial", "start free", "request a demo", "book a demo", "get started", "pricing",
                "for teams", "enterprise plan", "api docs"]
CORP_PHRASES = ["careers", "investors", "investor relations", "our solutions", "our services", "contact sales", "our clients",
                "about the company", "press releases", "sustainability report"]
PARKED_PHRASES = ["domain is for sale", "this domain may be for sale", "buy this domain", "domain for sale", "parked free", "this domain is parked",
                  "sedoparking", "parkingcrew", "bodis", "afternic", "dan.com", "hugedomains", "is available for purchase", "domain has expired"]
FORUM_PHRASES = ["forum", "forums", "threads", "replies", "members online", "new posts", "latest posts", "community", "discussions", "форум"]
GOV_PHRASES = ["official website of the", "government of", "ministry of", "official government", "gov.uk", ".gov"]
CHALLENGE_PHRASES = ["just a moment...", "checking your browser", "attention required! | cloudflare", "verify you are human",
                     "enable javascript and cookies to continue", "access denied", "captcha", "ddos protection by", "are you a robot"]

NEWS_SCHEMA = {"NewsArticle", "ReportageNewsArticle", "AnalysisNewsArticle", "LiveBlogPosting", "NewsMediaOrganization"}
ARTICLE_SCHEMA = {"Article", "BlogPosting", "NewsArticle", "ReportageNewsArticle", "AnalysisNewsArticle", "OpinionNewsArticle",
                  "LiveBlogPosting", "TechArticle", "ScholarlyArticle", "Report", "Recipe", "VideoGame", "Review"}
COMMERCE_SCHEMA = {"Product", "Offer", "AggregateOffer", "ProductGroup", "Store", "OnlineStore"}
SAAS_SCHEMA = {"SoftwareApplication", "WebApplication", "MobileApplication"}
FORUM_SCHEMA = {"DiscussionForumPosting", "SocialMediaPosting", "QAPage"}
GOV_SCHEMA = {"GovernmentOrganization", "GovernmentService", "GovernmentOffice"}
ORG_SCHEMA = {"Organization", "Corporation", "LocalBusiness"}

CCTLD_COUNTRY = {
    "uk": "GB", "de": "DE", "fr": "FR", "it": "IT", "es": "ES", "nl": "NL", "be": "BE", "at": "AT", "ch": "CH", "pl": "PL", "cz": "CZ",
    "sk": "SK", "hu": "HU", "ro": "RO", "bg": "BG", "gr": "GR", "pt": "PT", "se": "SE", "no": "NO", "dk": "DK", "fi": "FI", "ie": "IE",
    "ru": "RU", "ua": "UA", "tr": "TR", "jp": "JP", "kr": "KR", "cn": "CN", "in": "IN", "br": "BR", "mx": "MX", "ar": "AR", "cl": "CL",
    "co": "CO", "au": "AU", "nz": "NZ", "ca": "CA", "za": "ZA", "id": "ID", "vn": "VN", "th": "TH", "ph": "PH", "my": "MY", "sg": "SG",
    "il": "IL", "sa": "SA", "ae": "AE", "eg": "EG", "rs": "RS", "hr": "HR", "si": "SI", "lt": "LT", "lv": "LV", "ee": "EE", "us": "US",
}


def _texts(nodes) -> list[str]:
    return [_WS_RE.sub(" ", (n.text_content() or "")).strip() for n in nodes]


def _jsonld_types(doc) -> tuple[list[str], list[dict]]:
    types: list[str] = []
    objs: list[dict] = []
    for s in doc.xpath('//script[@type="application/ld+json"]'):
        raw = (s.text or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                data = json.loads(raw.replace("\n", " ").rstrip(";"))
            except json.JSONDecodeError:
                continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, list):
                stack.extend(cur)
            elif isinstance(cur, dict):
                t = cur.get("@type")
                if isinstance(t, str):
                    types.append(t)
                    objs.append(cur)
                elif isinstance(t, list):
                    types.extend(str(x) for x in t if isinstance(x, (str, int)))
                    objs.append(cur)
                for k in ("@graph", "mainEntity", "itemListElement", "publisher", "author", "item"):
                    if k in cur:
                        stack.append(cur[k])
    return types, objs


def _types_of(obj: dict) -> set[str]:
    """schema.org @type may be a string, a list of strings, or a URL - normalise to short names."""
    t = obj.get("@type")
    items = t if isinstance(t, list) else [t]
    return {str(x).rsplit("/", 1)[-1] for x in items if isinstance(x, (str, int))}


def _name(v: Any) -> str:
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list) and v:
        return _name(v[0])
    if isinstance(v, dict):
        return _name(v.get("@value") or v.get("name") or "")
    return ""


def extract_safe(html: str, url: str) -> dict[str, Any]:
    """Like extract(), but one malformed page can never crash a batch: errors become an
    'unparseable' feature dict (which the classifier treats as no usable content)."""
    try:
        return extract(html, url)
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "unparseable": True, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def extract(html: str, url: str) -> dict[str, Any]:
    """Return a JSON-serialisable feature dict for one page."""
    f: dict[str, Any] = {"url": url}
    if not html or not html.strip():
        f["empty"] = True
        return f
    try:
        doc = lxml.html.fromstring(html)
    except (etree.ParserError, ValueError):
        f["unparseable"] = True
        return f
    host = (urlsplit(url).hostname or "").lower()
    base_host = host[4:] if host.startswith("www.") else host

    title = (doc.findtext(".//title") or "").strip()
    meta = {}
    for m in doc.xpath("//meta[@name or @property]"):
        k = (m.get("name") or m.get("property") or "").strip().lower()
        if k and k not in meta:
            meta[k] = (m.get("content") or "").strip()
    f["title"] = title[:300]
    f["description"] = meta.get("description", meta.get("og:description", ""))[:500]
    f["og_type"] = meta.get("og:type", "")
    f["og_site_name"] = meta.get("og:site_name", "")[:200]
    f["og_locale"] = meta.get("og:locale", "")
    f["generator"] = meta.get("generator", "")[:100]
    f["has_published_time"] = bool(meta.get("article:published_time") or meta.get("og:article:published_time") or meta.get("pubdate")
                                   or meta.get("date") or meta.get("dc.date"))
    f["has_author_meta"] = bool(meta.get("author") or meta.get("article:author"))
    f["html_lang"] = (doc.get("lang") or doc.xpath("string(/html/@lang)") or "").strip()[:16]
    f["hreflangs"] = sorted({(l.get("hreflang") or "").lower() for l in doc.xpath('//link[@rel="alternate"][@hreflang]')})[:40]
    f["robots_noindex"] = "noindex" in meta.get("robots", "").lower()

    types, objs = _jsonld_types(doc)
    types += [t.rsplit("/", 1)[-1] for t in doc.xpath("//@itemtype") if isinstance(t, str)]
    f["schema_types"] = sorted(set(types))[:60]
    f["org_names"] = sorted({_name(o.get("name"))[:200] for o in objs
                             if _types_of(o) & (ORG_SCHEMA | {"NewsMediaOrganization"}) and _name(o.get("name"))})[:5]

    f["feed_links"] = [urljoin(url, l.get("href")) for l in doc.xpath('//link[@rel="alternate"][contains(@type,"rss") or contains(@type,"atom")]') if l.get("href")][:5]

    # body text
    for bad in doc.xpath("//script|//style|//noscript|//template|//svg"):
        bad.drop_tree() if bad.getparent() is not None else None
    body_text = _WS_RE.sub(" ", doc.text_content() if doc is not None else "").strip()
    f["word_count"] = len(body_text.split())
    low = body_text.lower()
    low_title = (title + " " + f["description"] + " " + f["og_site_name"]).lower()

    # links
    anchors = doc.xpath("//a[@href]")
    internal, article_like, dated = set(), set(), set()
    for a in anchors:
        href = urljoin(url, a.get("href").strip())
        parts = urlsplit(href)
        h = (parts.hostname or "").lower()
        h = h[4:] if h.startswith("www.") else h
        if h != base_host:
            continue
        path = parts.path or "/"
        if path in ("/", ""):
            continue
        internal.add(path)
        if _DATE_PATH_RE.search(path):
            dated.add(href)
            article_like.add(href)
        elif _SLUG_RE.search(path.lower()) or _ID_ARTICLE_RE.search(path):
            article_like.add(href)
    f["internal_link_count"] = len(internal)
    f["article_link_count"] = len(article_like)
    f["dated_link_count"] = len(dated)
    f["article_link_sample"] = sorted(article_like, key=lambda u: (u not in dated, -len(u)))[:10]

    biz = {"advertise": None, "contact": None, "about": None}
    for a in anchors:
        label = ((a.text_content() or "") + " " + (a.get("href") or "")).lower()
        href = urljoin(url, a.get("href").strip())
        if biz["advertise"] is None and any(k in label for k in ("advertis", "media kit", "mediakit", "reklam", "werbung", "publicit", "реклама")):
            biz["advertise"] = href
        if biz["contact"] is None and any(k in label for k in ("contact", "kontakt", "контакт", "contacto", "impressum")):
            biz["contact"] = href
        if biz["about"] is None and any(k in label for k in ("about", "за нас", "über uns", "chi siamo", "qui sommes")):
            biz["about"] = href
    f["business_links"] = {k: v[:300] for k, v in biz.items() if v}
    f["time_elements"] = len(doc.xpath("//time"))
    f["byline_elements"] = len(doc.xpath('//*[contains(@class,"byline") or contains(@class,"author") or @rel="author"]'))
    f["article_elements"] = len(doc.xpath("//article"))
    nav_text = " ".join(_texts(doc.xpath("//nav//a|//header//a|//*[contains(@class,'menu')]//a")))[:4000].lower()
    f["nav_text"] = nav_text[:1500]

    f["password_inputs"] = len(doc.xpath('//input[@type="password"]'))
    f["price_mentions"] = len(_PRICE_RE.findall(body_text[:200_000]))
    f["iframes"] = len(doc.xpath("//iframe"))
    f["challenge_page"] = any(p in (title.lower() + " " + low[:2000]) for p in CHALLENGE_PHRASES) and f["word_count"] < 400

    def count(phrases: list[str], text: str) -> list[str]:
        return [p for p in phrases if p in text]

    f["ecom_phrases"] = count(ECOM_PHRASES, low[:100_000])
    f["saas_phrases"] = count(SAAS_PHRASES, (nav_text + " " + low[:20_000]))
    f["corp_phrases"] = count(CORP_PHRASES, (nav_text + " " + low[:30_000]))
    f["parked_phrases"] = count(PARKED_PHRASES, (low_title + " " + low[:20_000]))
    f["forum_phrases"] = count(FORUM_PHRASES, (low_title + " " + nav_text))
    f["gov_phrases"] = count(GOV_PHRASES, (low_title + " " + low[:5000]))
    f["tool_phrases"] = count(TOOL_KEYWORDS, low_title)

    topic_text = f"{low_title} {nav_text}"
    topics = Counter()
    for cat, words in TOPIC_KEYWORDS.items():
        for w in words:
            if re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", topic_text):
                topics[cat] += 2 if w in low_title else 1
    f["topic_hits"] = dict(topics)

    # technology fingerprints (static) used as classification signals only
    reg = load_registry()
    cats: dict[str, list[str]] = {}
    scripts = [s.get("src") or "" for s in lxml.html.fromstring(html).xpath("//script[@src]")]
    for v in reg.vendors:
        hit = any(p.search(s) for p in v.script for s in scripts) or any(p.search(html[:400_000]) for p in v.html)
        if hit:
            cats.setdefault(v.category, []).append(v.key)
    f["tech"] = cats
    return f


def country_signals(features: list[dict[str, Any]], host: str) -> list[str]:
    out: list[str] = []
    tld = host.rsplit(".", 1)[-1].lower()
    if tld in CCTLD_COUNTRY:
        out.append(CCTLD_COUNTRY[tld])
    for f in features:
        for src in [f.get("html_lang", ""), f.get("og_locale", "")]:
            src = src.replace("_", "-")
            if "-" in src:
                cc = src.split("-")[-1].upper()
                if len(cc) == 2 and cc.isalpha():
                    out.append(cc)
    seen: list[str] = []
    for c in out:
        if c not in seen:
            seen.append(c)
    return seen[:5]
