"""Generic main-content fetch/parse for arbitrary discovered sites.

DESIGN_01_category-discovery.md §5. This is Increment 3 of that design's rollout
(§13): the fetch/parse mechanism itself, tested against recorded/mocked real pages.
It deliberately does NOT do site/URL discovery (sitemap crawling, §4 tier 2) yet —
that's Increment 4's pilot, which wires this together with category_discovery.py
and site_intelligence.py against a real source type. This module only answers:
"given one URL, get its real article content or an honest error — never fabricate."

Why trafilatura (new dependency, lazy-imported per CLAUDE.md's "Conventions" — same
pattern as playwright/pytrends/anthropic/PIL): today's parsers are hand-written per
channel (BeautifulSoup for Forums/Quora, feedparser for News) because those sites'
HTML shapes are known in advance. An open-ended set of discovered sites has no such
shape in common, so a purpose-built main-content extractor is a better fit than a
hand-rolled heuristic. Verified live against a real thebetterindia.com article
(2026-09-13): correct title/author/date and 14,643 chars of genuine body text, zero
boilerplate — not a hypothetical, an actual run.

Failure/fallback path, exactly as specified in §5 (mirrors scrapers/ecommerce.py's
"never fabricate on failure" contract):
  1. Fetch via http_client.get_session() — Ground Rule #2, no bypass of the shared
     retry/rate-limit policy. Deliberately does NOT use trafilatura.fetch_url(),
     which would perform its own uncoordinated HTTP request.
  2. Check the raw fetched HTML for a bot-block/CAPTCHA presentation BEFORE trusting
     any extracted content — reusing, not reinventing, the exact marker lists proven
     live this session in scrapers/ecommerce.py (_BLOCK_MARKERS, _CAPTCHA_HTML_MARKERS).
     A hit here returns an honest error, nothing is extracted.
  3. Run trafilatura.extract(). None, or content shorter than ecommerce.py's proven
     _MIN_CONTENT_LEN threshold, returns an honest error, nothing stored.
  4. Only a real, non-blocked, non-trivially-short extraction is returned as ok=True.

Note on step 2 versus ecommerce.py's `_looks_blocked`: ecommerce.py's version also
applies _MIN_CONTENT_LEN as a *pre*-extraction signal, because Playwright gives it
already-rendered *visible* text (page.inner_text('body')), where a short body is
itself suspicious. Here we only have raw HTML at that point — naturally many
thousands of characters regardless of whether the real article content is blocked —
so length is only a meaningful signal *after* trafilatura extraction (step 3), not
before.

A real false positive, found empirically while writing this module's tests (not
hypothetical): a genuine, fully-accessible thebetterindia.com article's raw HTML
contains the literal string "recaptcha" 8 times and "captcha" 15 times — not because
the page is blocked, but because its comment/newsletter form embeds a reCAPTCHA
widget, like an enormous share of real WordPress-family sites. ecommerce.py's
_CAPTCHA_HTML_MARKERS check (and its bare "captcha" entry in _BLOCK_MARKERS) is
safe there because Playwright's page.content() is checked as a *secondary* signal
alongside already-short *visible* text — a real content-rich page rarely trips both.
Applied to raw, un-rendered HTML alone, checking those same markers pre-extraction
would misclassify this real, fully-legitimate article as blocked. So: the bare
"captcha" marker and the whole _CAPTCHA_HTML_MARKERS list are deliberately NOT
checked pre-extraction here — only the more explicit, interstitial-page-specific
_BLOCK_MARKERS phrases are ("access denied", "verify you are human", "just a
moment", etc. — phrases a real article is very unlikely to contain incidentally).
The CAPTCHA-specific markers are instead checked only as an enrichment to the
*post-extraction* too-short/absent-content error, where they can only sharpen an
already-correct "no real content" verdict, never independently override a page that
successfully yielded real, substantial content.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from scrapers.ecommerce import _BLOCK_MARKERS, _CAPTCHA_HTML_MARKERS, _MIN_CONTENT_LEN

CHANNEL = "generic_site"


def _default_fetch(url: str):
    """Real network path — same shared retry/rate-limit policy every other channel
    uses (Ground Rule #2). Matches scrapers/news.py's _default_fetch/fetch_fn
    convention exactly, so tests inject a fake fetch_fn instead of monkeypatching
    http_client, and no real network call happens in the automated test suite."""
    from http_client import get_session

    return get_session().get(url)


# Deliberately excludes the bare "captcha" marker — see module docstring's "real false
# positive" note: a real, fully-accessible article's raw HTML routinely embeds a
# reCAPTCHA widget for an unrelated comment/newsletter form. The remaining phrases are
# explicit interstitial-page language a normal article won't contain incidentally.
_PRE_EXTRACT_MARKERS = [m for m in _BLOCK_MARKERS if m != "captcha"]


def _looks_blocked_pre_extract(html: str) -> Dict[str, Any]:
    """Marker-only block check on raw fetched HTML, before extraction is attempted.
    See module docstring for why no length check and no CAPTCHA-widget check happen
    at this stage."""
    low = (html or "").lower()
    for marker in _PRE_EXTRACT_MARKERS:
        if marker in low:
            return {"blocked": True, "reason": f"page contains block marker {marker!r}"}
    return {"blocked": False, "reason": None}


def _captcha_hint(html: str) -> Optional[str]:
    """Post-extraction-only enrichment: did the raw HTML also contain CAPTCHA-widget
    evidence? Used to sharpen an already-correct too-short/absent-content error
    message, never to independently veto a page that yielded real content."""
    low = (html or "").lower()
    if "captcha" in low:
        return "captcha"
    for marker in _CAPTCHA_HTML_MARKERS:
        if marker in low:
            return marker
    return None


def fetch_and_extract(url: str, *,
                      fetch_fn: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """Fetch one URL and extract its main content. Never fabricates: any failure
    (fetch error, HTTP error status, detected block, trafilatura finding nothing or
    too little) comes back as {"ok": False, "error": "..."} with no invented text.

    ``fetch_fn`` defaults to the real network path (_default_fetch, via
    http_client.get_session()); tests inject a fake one, matching scrapers/news.py's
    convention — the response only needs a ``.text`` and ``.status_code``.

    Returns on success: {"ok": True, "url", "title", "text", "author", "published",
    "raw_html"} — field names chosen to map directly onto the item shape every other
    channel already produces (title/text/link/published), plus raw_html for the
    raw-content retention this design requires (migrations.py's items.raw_html,
    _m003_category_discovery).
    """
    fetch = fetch_fn or _default_fetch

    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "empty url", "url": url}

    try:
        resp = fetch(url)
    except Exception as exc:
        return {"ok": False, "error": f"fetch failed: {exc}", "url": url}

    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "url": url}

    html = resp.text or ""

    block = _looks_blocked_pre_extract(html)
    if block["blocked"]:
        return {"ok": False, "error": f"blocked: {block['reason']}", "url": url}

    try:
        import trafilatura
    except Exception:
        return {"ok": False,
                "error": "trafilatura is not installed. Run `pip install trafilatura`. "
                         "Generic site fetch was skipped — no data fabricated.",
                "url": url}

    extracted = trafilatura.extract(html, url=url, with_metadata=True,
                                    include_comments=False, output_format="json")
    if not extracted:
        hint = _captcha_hint(html)
        suffix = f" (page HTML also contains {hint!r} — possibly CAPTCHA-walled)" if hint else ""
        return {"ok": False,
                "error": f"trafilatura found no extractable main content{suffix}",
                "url": url}

    try:
        meta = json.loads(extracted)
    except Exception:
        meta = {"text": extracted}

    text = (meta.get("text") or "").strip()
    if len(text) < _MIN_CONTENT_LEN:
        hint = _captcha_hint(html)
        suffix = f" (page HTML also contains {hint!r} — possibly CAPTCHA-walled)" if hint else ""
        return {"ok": False,
                "error": f"extracted content too short ({len(text)} chars, "
                         f"min {_MIN_CONTENT_LEN}) — likely blocked/boilerplate page{suffix}",
                "url": url}

    return {
        "ok": True,
        "url": url,
        "title": meta.get("title") or "",
        "text": text,
        "author": meta.get("author") or "",
        "published": meta.get("date") or "",
        "raw_html": html,
    }
