"""Rendered-page inspection with Playwright + Chromium.

* Every browser request passes a route handler that refuses non-http(s) schemes and hosts that
  resolve to private / internal addresses (SSRF guard for the browser).
* Images, fonts and media are aborted after being recorded (bandwidth), scripts/XHR proceed.
* Anti-bot challenges, CAPTCHAs, logins and paywalls are detected and reported as blocked,
  never bypassed.
* Captured: network request URLs, vendor JS globals, Prebid runtime state (configured,
  requested and responding bidders), GPT slots, and DOM ad placement geometry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.adtech.registry import load_registry
from app.core.config import get_settings
from app.services.safe_fetch import FetchBlocked, SafeFetcher, resolve_public

log = logging.getLogger(__name__)

CHALLENGE_MARKERS = ("just a moment", "checking your browser", "verify you are human", "attention required",
                     "captcha", "are you a robot", "access denied", "enable javascript and cookies")

_PAGE_SCRIPT = r"""
async (GLOBALS) => {
  const out = {globals:{}, prebid:[], gpt:null, placements:[], video:{}, title: document.title || '', text_len: (document.body && document.body.innerText || '').length};
  const get = (path) => { try { return path.split('.').reduce((o,k) => (o == null ? undefined : o[k]), window); } catch (e) { return undefined; } };
  for (const g of GLOBALS) { const v = get(g); out.globals[g] = (v !== undefined && v !== null && v !== false); }
  const names = new Set(['pbjs']);
  try { (window._pbjsGlobals || []).forEach(n => names.add(n)); } catch (e) {}
  for (const n of names) {
    const p = window[n];
    if (!p || typeof p !== 'object' || !p.version) continue;
    const inst = {global: n, version: String(p.version), configured_bidders: [], requested_bidders: [], responding_bidders: [], ad_units: 0, s2s_bidders: [], ad_unit_sizes: []};
    try { const au = p.adUnits || []; inst.ad_units = au.length;
          au.forEach(u => { (u.bids || []).forEach(b => b && b.bidder && inst.configured_bidders.push(b.bidder));
                            try { const s = (u.mediaTypes && u.mediaTypes.banner && u.mediaTypes.banner.sizes) || u.sizes || []; s.forEach(z => inst.ad_unit_sizes.push(Array.isArray(z) ? z.join('x') : String(z))); } catch (e) {} }); } catch (e) {}
    try { (p.getEvents ? p.getEvents() : []).forEach(ev => {
            const a = ev && ev.args; if (!a) return;
            if (ev.eventType === 'bidRequested' && a.bidderCode) inst.requested_bidders.push(a.bidderCode);
            if (ev.eventType === 'bidResponse' && a.bidderCode) inst.responding_bidders.push(a.bidderCode);
            if (ev.eventType === 'auctionInit' && a.adUnits) a.adUnits.forEach(u => (u.bids || []).forEach(b => b && b.bidder && inst.configured_bidders.push(b.bidder)));
          }); } catch (e) {}
    try { const s2s = p.getConfig && p.getConfig('s2sConfig'); [].concat(s2s || []).forEach(c => ((c && c.bidders) || []).forEach(b => inst.s2s_bidders.push(b))); } catch (e) {}
    for (const k of ['configured_bidders','requested_bidders','responding_bidders','s2s_bidders','ad_unit_sizes']) inst[k] = [...new Set(inst[k])].slice(0, 80);
    out.prebid.push(inst);
  }
  try {
    if (window.googletag && googletag.pubadsReady && googletag.pubads) {
      const slots = googletag.pubads().getSlots() || [];
      out.gpt = {pubads_ready: true, slots: slots.slice(0, 100).map(s => ({
        path: s.getAdUnitPath(), div: s.getSlotElementId(),
        sizes: (s.getSizes() || []).map(z => typeof z === 'string' ? z : (z && z.getWidth ? z.getWidth() + 'x' + z.getHeight() : String(z)))
      }))};
    }
  } catch (e) {}
  const vw = window.innerWidth, vh = window.innerHeight;
  const sel = 'ins.adsbygoogle,[id^="div-gpt-ad"],[data-google-query-id],[id^="google_ads_iframe"],[data-ad-slot],[data-ad-unit],[class*="ad-slot"],[class*="adslot"],[class*="ad-container"],[class*="ad-wrapper"],[id^="ad-"],[id*="-ad-"],[class*="advert"]';
  const nodes = new Set(document.querySelectorAll(sel));
  if (out.gpt) out.gpt.slots.forEach(s => { const el = s.div && document.getElementById(s.div); if (el) nodes.add(el); });
  const fixedAncestor = (el) => { let e = el; for (let i = 0; e && i < 6; i++, e = e.parentElement) { const p = getComputedStyle(e).position; if (p === 'fixed' || p === 'sticky') return p; } return null; };
  let n = 0;
  for (const el of nodes) {
    if (n++ > 120) break;
    if ([...nodes].some(o => o !== el && o.contains(el))) continue; // keep outermost container
    const r = el.getBoundingClientRect();
    const pos = fixedAncestor(el);
    const absTop = r.top + window.scrollY;
    let type = 'other';
    if (pos === 'fixed' && r.width > vw * 0.5 && (r.top > vh * 0.7 || r.bottom < vh * 0.3)) type = 'anchor';
    else if (pos) type = 'sticky';
    else if (el.closest('aside,[class*="sidebar"],[id*="sidebar"]') || (r.left > vw * 0.6 && r.width <= 340 && r.width > 0)) type = 'sidebar';
    else if (absTop < 320 && r.width >= 700) type = 'header';
    else if (el.closest('article,[class*="article-body"],[class*="post-content"],[class*="entry-content"],[itemprop="articleBody"]')) type = 'in_content';
    const iframe = el.querySelector('iframe');
    out.placements.push({type, w: Math.round(r.width), h: Math.round(r.height), top: Math.round(absTop),
      id: (el.id || '').slice(0, 80), cls: (el.className && el.className.toString ? el.className.toString() : '').slice(0, 80),
      has_iframe: !!(iframe && iframe.getBoundingClientRect().width > 0), lazy_attr: !!(el.getAttribute('data-lazy') || el.getAttribute('loading') === 'lazy')});
  }
  out.video = {video_elements: document.querySelectorAll('video').length, ima: !!(window.google && window.google.ima)};
  // ---- cookie-consent (CMP) state: in the EU many sites load NO ads until consent is given
  const consent = {cmps: [], banner_visible: false, tcf: null};
  const cmpGlobals = {OneTrust: 'onetrust', Optanon: 'onetrust', Didomi: 'didomi', _sp_: 'sourcepoint', Cookiebot: 'cookiebot',
                      UC_UI: 'usercentrics', __cmp: 'tcf_v1', truste: 'trustarc', klaro: 'klaro', _iub: 'iubenda',
                      axeptioSDK: 'axeptio', googlefc: 'google_funding_choices', __tcfapi: 'tcf_v2', __gpp: 'gpp'};
  for (const [g, name] of Object.entries(cmpGlobals)) { try { if (window[g]) consent.cmps.push(name); } catch (e) {} }
  const bannerSel = ['#onetrust-banner-sdk', '#onetrust-consent-sdk', '#didomi-host', '#didomi-notice', 'iframe[id^="sp_message_iframe"]',
    '[id^="sp_message_container"]', '#CybotCookiebotDialog', '#usercentrics-root', '.fc-consent-root', '#qc-cmp2-container',
    '.qc-cmp2-container', '#truste-consent-track', '#cmpbox', '.cmp-container', '[class*="consent-banner"]', '[id*="cookie-banner"]'];
  for (const sel of bannerSel) {
    try { const el = document.querySelector(sel); if (el) { const r = el.getBoundingClientRect();
          if (r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden') { consent.banner_visible = true; consent.banner = sel; break; } } } catch (e) {}
  }
  if (typeof window.__tcfapi === 'function') {
    consent.tcf = await new Promise((resolve) => {
      const t = setTimeout(() => resolve({timeout: true}), 1500);
      try { window.__tcfapi('getTCData', 2, (d, ok) => { clearTimeout(t);
              resolve(ok && d ? {gdprApplies: d.gdprApplies, cmpStatus: d.cmpStatus, eventStatus: d.eventStatus, cmpId: d.cmpId,
                                 purpose1: !!(d.purpose && d.purpose.consents && d.purpose.consents['1'])} : {ok: false}); });
      } catch (e) { clearTimeout(t); resolve({error: String(e)}); }
    });
  }
  consent.cmps = [...new Set(consent.cmps)];
  // Consent is "pending" when a banner is showing, or TCF says GDPR applies and storage consent (purpose 1) is not given.
  consent.pending = consent.banner_visible || !!(consent.tcf && consent.tcf.gdprApplies && consent.tcf.purpose1 === false);
  out.consent = consent;
  return out;
}
"""


# ---- cookie-consent acceptance (CONSENT_MODE=accept) ------------------------------------------
# In the EU most ad-supported sites load no ads until "Accept" is clicked. To observe the ad stack a
# normal visitor sees, the renderer can accept the banner in its own throwaway browser context.
# It never clicks subscribe / paid / "ad-free" options and records exactly what it clicked.
CONSENT_SELECTORS = [
    "#onetrust-accept-btn-handler",                                  # OneTrust
    "button.sp_choice_type_11",                                      # Sourcepoint (iframe): "accept all"
    "#didomi-notice-agree-button",                                   # Didomi
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",        # Cookiebot
    "#CybotCookiebotDialogBodyButtonAccept",
    "[data-testid='uc-accept-all-button']",                          # Usercentrics (open shadow DOM)
    ".qc-cmp2-summary-buttons button[mode='primary']",               # Quantcast
    "button.fc-cta-consent",                                         # Google Funding Choices
    "#truste-consent-button",                                        # TrustArc
    "#cmpbntyestxt", "a.cmpboxbtnyes",                               # consentmanager.net
    "button[data-cookiebanner='accept_button']",
    ".iubenda-cs-accept-btn",                                        # iubenda
    "#axeptio_btn_acceptAll",                                        # Axeptio
]
ACCEPT_TEXT_RE = re.compile(
    r"^\s*(accept( all| all cookies| cookies| and continue| & continue)?|i accept|agree|i agree|agree( and| &) (continue|close)|allow all( cookies)?|"
    r"alle akzeptieren|akzeptieren( und weiter| & weiter)?|zustimmen( und weiter)?|einverstanden|alle annehmen|"
    r"tout accepter|accepter( et continuer| et fermer)?|j'accepte|"
    r"aceptar( todo| todas| y continuar)?|acepto|accetta( tutto| e continua)?|accetto|"
    r"aceitar( tudo| todos)?|zaakceptuj( wszystkie)?|akceptuj(ę)?|alles accepteren|accepteren|akkoord|"
    r"godkänn( alla)?|acceptera( alla)?|accepter alle|tillad alle|godta( alle)?|hyväksy( kaikki)?|"
    r"приемам|приемам всички|приеми( всички)?|съгласен|съгласна|принять( все)?|согласен|прийняти|"
    r"kabul et|tümünü kabul et|elfogadom|összes elfogadása|souhlasím|přijmout vše|súhlasím|prijať všetko|"
    r"sutinku|piekrītu|nõustun|prihvati( sve)?|прихвати|sprejmi vse|αποδοχή( όλων)?|accept toate|sunt de acord|"
    r"ok|got it)\s*[.!]?\s*$", re.I)
AVOID_TEXT_RE = re.compile(r"(abo|subscri|pur\b|ad-?free|werbefrei|sans pub|€|\$|pay|login|sign in|anmelden|register)", re.I)


async def accept_consent(page) -> dict:
    """Try to accept a cookie-consent banner. Returns a record of what happened."""
    out: dict = {"mode": "accept", "clicked": None}
    frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
    for frame in frames:
        for sel in CONSENT_SELECTORS:
            try:
                loc = frame.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    txt = (await loc.inner_text(timeout=1000)).strip()[:60]
                    if AVOID_TEXT_RE.search(txt):
                        continue
                    await loc.click(timeout=3000)
                    out.update(clicked=sel, text=txt, frame=(frame.url or "")[:200])
                    return out
            except Exception:  # noqa: BLE001 - detached frames, timeouts
                continue
    for frame in frames:
        try:
            buttons = frame.get_by_role("button", name=ACCEPT_TEXT_RE)
            for i in range(min(await buttons.count(), 6)):
                b = buttons.nth(i)
                txt = (await b.inner_text(timeout=1000)).strip()
                if len(txt) > 40 or AVOID_TEXT_RE.search(txt) or not await b.is_visible():
                    continue
                await b.click(timeout=3000)
                out.update(clicked="text-match", text=txt[:60], frame=(frame.url or "")[:200])
                return out
        except Exception:  # noqa: BLE001
            continue
    return out


@dataclass
class RenderResult:
    url: str
    final_url: str | None = None
    ok: bool = False
    status: int | None = None
    blocked_reason: str | None = None
    error: str | None = None
    network: list[dict[str, Any]] = field(default_factory=list)
    script_urls: list[str] = field(default_factory=list)
    page: dict[str, Any] = field(default_factory=dict)
    html: str = ""
    elapsed_ms: int = 0
    browser_version: str | None = None


class _HostGuard:
    def __init__(self) -> None:
        self.cache: dict[str, bool] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme in ("data", "blob", "about"):
            return True
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        h = parts.hostname
        if h not in self.cache:
            try:
                await resolve_public(h, parts.port or (443 if parts.scheme == "https" else 80))
                self.cache[h] = True
            except (FetchBlocked, Exception):
                self.cache[h] = False
        return self.cache[h]


class Renderer:
    """`async with Renderer() as r: await r.render(url)`; one browser, isolated context per page."""

    def __init__(self) -> None:
        self.s = get_settings()
        self._pw = None
        self._browser = None
        self._sem = asyncio.Semaphore(max(1, self.s.playwright_concurrency))
        self._robots: SafeFetcher | None = None
        self._ua: str | None = None

    async def __aenter__(self) -> "Renderer":
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        kwargs: dict[str, Any] = {"headless": True, "args": ["--disable-dev-shm-usage", "--no-first-run", "--mute-audio"]}
        exe = getattr(self.s, "chromium_executable", None)
        if exe:
            kwargs["executable_path"] = exe
        self._browser = await self._pw.chromium.launch(**kwargs)
        # Identify honestly: the browser's normal UA (without the "Headless" marker) plus our bot token,
        # the same convention major crawlers use.
        major = (self._browser.version or "").split(".")[0] or "120"
        self._ua = (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 "
                    f"Safari/537.36 {self.s.user_agent}")
        if self.s.respect_robots_txt:
            self._robots = await SafeFetcher().__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._robots is not None:
            await self._robots.__aexit__(None, None, None)
        try:
            if self._browser:
                await self._browser.close()
        finally:
            if self._pw:
                await self._pw.stop()

    async def render(self, url: str) -> RenderResult:
        async with self._sem:
            return await self._render(url)

    async def _render(self, url: str) -> RenderResult:
        res = RenderResult(url=url, browser_version=self._browser.version if self._browser else None)
        start = time.monotonic()
        guard = _HostGuard()
        if not await guard.allowed(url):
            res.blocked_reason = "SSRF guard: target not allowed"
            return res
        if self._robots is not None and not await self._robots.allowed_by_robots(url):
            res.blocked_reason = "robots.txt disallows"
            return res
        ctx = await self._browser.new_context(
            user_agent=self._ua or self.s.http_user_agent,
            viewport={"width": 1366, "height": 900},
            java_script_enabled=True,
            service_workers="block",
            accept_downloads=False,
        )
        ctx.set_default_navigation_timeout(self.s.playwright_timeout_ms)
        page = await ctx.new_page()
        reg = load_registry()

        async def route(route):
            req = route.request
            u = req.url
            if not await guard.allowed(u):
                res.network.append({"url": u[:500], "type": req.resource_type, "blocked": "ssrf"})
                await route.abort()
                return
            if len(res.network) < 3000:
                res.network.append({"url": u[:1000], "type": req.resource_type})
            if req.resource_type == "script":
                res.script_urls.append(u[:1000])
            if req.resource_type in ("image", "media", "font"):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route)
        page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
        try:
            resp = await page.goto(url, wait_until="domcontentloaded")
            res.status = resp.status if resp else None
            res.final_url = page.url
            # let the page (and any consent banner) initialise
            await page.wait_for_timeout(self.s.playwright_settle_ms // 2)
            consent_action = {"mode": self.s.consent_mode, "clicked": None}
            if self.s.consent_mode == "accept":
                consent_action = await accept_consent(page)
                if consent_action.get("clicked"):
                    # ad stacks start after consent: give them time
                    await page.wait_for_timeout(self.s.playwright_settle_ms // 2)
            # scroll a few screens to trigger lazy-loaded slots
            for _ in range(4):
                await page.mouse.wheel(0, 900)
                await page.wait_for_timeout(600)
            await page.wait_for_timeout(self.s.playwright_settle_ms // 2)
            data = await page.evaluate(_PAGE_SCRIPT, reg.all_globals())
            data["consent_action"] = consent_action
            if consent_action.get("clicked") and data.get("consent"):
                data["consent"]["accepted_by_robot"] = True
            res.page = data
            res.html = (await page.content())[: self.s.http_max_bytes]
            title = (data.get("title") or "").lower()
            if any(m in title for m in CHALLENGE_MARKERS) and data.get("text_len", 0) < 2000:
                res.blocked_reason = "anti-bot challenge page (not bypassed)"
            elif res.status and res.status >= 400:
                res.blocked_reason = f"HTTP {res.status}"
            else:
                res.ok = True
        except Exception as exc:  # timeouts, navigation errors, crashed pages
            res.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            res.elapsed_ms = int((time.monotonic() - start) * 1000)
            await ctx.close()
        return res


def render_to_json(r: RenderResult) -> str:
    return json.dumps({k: getattr(r, k) for k in ("url", "final_url", "ok", "status", "blocked_reason", "error")})
