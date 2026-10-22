"""Cheap, network-free exclusion rules used by the qualify stage."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classify.rules import GOV_SUFFIXES
from app.models import ExclusionRule

# Large platforms / infrastructure that are never publisher prospects. Editable via the
# exclusion list in Settings; this is only a conservative built-in floor.
BUILTIN_REGISTRABLE = {
    "google.com", "youtube.com", "facebook.com", "instagram.com", "whatsapp.com", "twitter.com", "x.com", "tiktok.com",
    "linkedin.com", "microsoft.com", "live.com", "office.com", "bing.com", "apple.com", "icloud.com", "amazon.com",
    "amazonaws.com", "cloudfront.net", "akamaihd.net", "akamaized.net", "cloudflare.com", "fastly.net", "googleapis.com",
    "gstatic.com", "doubleclick.net", "googlesyndication.com", "googleusercontent.com", "gmail.com", "yahoo.co.jp",
    "netflix.com", "spotify.com", "paypal.com", "zoom.us", "dropbox.com", "github.com", "githubusercontent.com",
    "wikipedia.org", "wikimedia.org", "openai.com", "chatgpt.com", "claude.ai", "anthropic.com", "baidu.com", "qq.com",
    "vk.com", "ok.ru", "telegram.org", "t.me", "discord.com", "slack.com", "salesforce.com", "adobe.com", "ebay.com",
    "aliexpress.com", "alibaba.com", "temu.com", "shein.com", "walmart.com", "booking.com", "airbnb.com", "pinterest.com",
}
# Deliberately narrow: substrings like "sex" would wrongly hit e.g. sussex/essex news sites.
ADULT_RE = re.compile(r"(porn|xxx|xnxx|xvideos|xhamster|hentai|camgirl|onlyfans|redtube|youporn|chaturbate|stripchat|spankbang)")
SUSPICIOUS_RE = re.compile(r"(torrent|warez|keygen|crackz|1337x|piratebay|rarbg|yts\.|limetorrents|nyaa\.|fitgirl)")
INFRA_HOST_RE = re.compile(r"^(api|cdn|static|img|images|assets|auth|login|accounts|mail|smtp|status|admin|dashboard|app|apps|my)\.")


@dataclass
class ExclusionDecision:
    excluded: bool
    reason: str | None = None


def load_rules(db: Session) -> list[ExclusionRule]:
    return list(db.scalars(select(ExclusionRule)))


def check(host: str, registrable: str, rules: list[ExclusionRule]) -> ExclusionDecision:
    for r in rules:
        p = r.pattern.lower()
        if (r.kind == "host" and host == p) or (r.kind == "registrable" and registrable == p) \
                or (r.kind == "suffix" and host.endswith(p)) or (r.kind == "keyword" and p in host):
            return ExclusionDecision(True, f"exclusion list ({r.kind}={r.pattern}): {r.reason}")
    if host.endswith(GOV_SUFFIXES) or registrable.endswith(GOV_SUFFIXES):
        return ExclusionDecision(True, "government domain")
    if registrable in BUILTIN_REGISTRABLE:
        return ExclusionDecision(True, "large platform / infrastructure domain")
    if ADULT_RE.search(host):
        return ExclusionDecision(True, "adult content keyword in domain (unsuitable)")
    if SUSPICIOUS_RE.search(host):
        return ExclusionDecision(True, "unsuitable keyword in domain (piracy)")
    if INFRA_HOST_RE.match(host) and host != registrable:
        return ExclusionDecision(True, "infrastructure / application subdomain")
    return ExclusionDecision(False)
