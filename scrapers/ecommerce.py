"""E-commerce collection via Playwright (rendered pages).

User-supplied product / category / search URLs. Extracts title, rendered text, review
text, and image URLs. Where a marketplace loads reviews via an internal JSON/XHR
endpoint, we intercept those responses and mine them too (many marketplaces do this).
Per-URL proxy is supported.

Snapshot semantics: each run captures the page as it is *now*. Scheduled repeat runs
build a price/review time series — there is NO historical backfill. This is stated in
the export Methodology and the UI.

Playwright is imported lazily so the rest of the tool (and the test suite) never
requires a browser to be installed.

Live-verified across two real Malaysian marketplaces: Shopee returns a soft bot-block
("Page Unavailable... Sorry, something went wrong. Please log in and try again") for
EVERY headless request, regardless of query — real page title, near-empty real body.
Lazada's product/search pages render real content (titles, prices, listings) — verified
live with actual Maggi products and prices — but its review section did not trigger any
XHR matching the review-endpoint heuristic even after scrolling, so review-specific
extraction is unverified there; page-level text (description, price context) still
captures real signal. Rather than chase Lazada's exact review-tab UI sequence (fragile,
site-specific, could break on the next redesign — precisely what this tool avoids
investing in per its own philosophy), the fix here is a correctness one that applies to
EVERY marketplace: a blocked/error page must never be silently stored as if it were
real content. Before this fix it was — a real bug, confirmed live on Shopee (0 errors
logged, 1 item stored with 0 chars of real text).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from scrapers.base import ScrapeResult

CHANNEL = "ecommerce"

# Heuristics for spotting review/ratings XHR responses by URL.
_REVIEW_URL_HINTS = ["review", "ratings", "feedback", "comment", "/qa", "questions"]
_PRICE_RE = re.compile(r"(?:[$£€¥₹]|\bRp\b|\bS\$)\s?\d[\d.,]*")

# Markers confirmed live in real marketplace bot-block/error pages (Shopee's
# "Page Unavailable" wall, generic CAPTCHA/verification interstitials).
_BLOCK_MARKERS = ["page unavailable", "something went wrong", "please log in and try again",
                  "access denied", "unusual traffic", "are you a human", "are you a robot",
                  "check if you are a robot", "verify you are human", "captcha",
                  "just a moment", "enable javascript and cookies"]
# CAPTCHA widget providers, checked against the raw page HTML (not just visible text).
# Verified live: a Lazada product page showed a reCAPTCHA modal ("We need to check if
# you are a robot") that page.inner_text('body') did NOT capture at all — it's rendered
# in an iframe, invisible to text-based extraction — while the underlying page still
# reported a plausible-looking body length (732 chars, above _MIN_CONTENT_LEN), so the
# text-only checks silently missed it. "recaptcha" WAS present in page.content() (the
# raw HTML) even though absent from the rendered text. This is why block detection
# must check raw HTML too, not just inner_text.
_CAPTCHA_HTML_MARKERS = ["recaptcha", "hcaptcha", "cf-turnstile", "funcaptcha", "arkose"]
# A real product/search/category page has far more rendered text than this. Below the
# threshold with no explicit marker is still suspicious for a page that's supposed to
# be rich e-commerce content — treated as likely-blocked rather than assumed legitimate.
_MIN_CONTENT_LEN = 300


def _looks_blocked(body_text: str, html: Optional[str] = None) -> Dict[str, Any]:
    """Detect a bot-block/error/CAPTCHA page. Checks the VISIBLE text first (catches
    Shopee-style full-page walls), then the raw HTML for CAPTCHA widget markers (catches
    modal/iframe-based challenges that inner_text never surfaces — see module notes)."""
    low = (body_text or "").strip().lower()
    for marker in _BLOCK_MARKERS:
        if marker in low:
            return {"blocked": True, "reason": f"page contains block marker {marker!r}"}
    if html:
        html_low = html.lower()
        for marker in _CAPTCHA_HTML_MARKERS:
            if marker in html_low:
                return {"blocked": True,
                       "reason": f"CAPTCHA widget ({marker!r}) present in page HTML — likely "
                                f"a modal/iframe challenge not visible to text extraction"}
    if len(low) < _MIN_CONTENT_LEN:
        return {"blocked": True, "reason": f"only {len(low)} chars of rendered content "
                                          f"(expected a real product/search page)"}
    return {"blocked": False, "reason": None}


def looks_like_review_endpoint(url: str) -> bool:
    u = url.lower()
    return any(h in u for h in _REVIEW_URL_HINTS)


def extract_price(text: str) -> Optional[str]:
    m = _PRICE_RE.search(text or "")
    return m.group(0) if m else None


def mine_review_json(payload: Any, out: List[str], depth: int = 0) -> None:
    """Best-effort: pull free-text review strings out of an arbitrary JSON blob."""
    if depth > 8:
        return
    if isinstance(payload, dict):
        for k, v in payload.items():
            if isinstance(v, str) and k.lower() in {"review", "reviewtext", "content", "text",
                                                     "comment", "body", "snippet"} and len(v) > 15:
                out.append(v)
            else:
                mine_review_json(v, out, depth + 1)
    elif isinstance(payload, list):
        for item in payload:
            mine_review_json(item, out, depth + 1)


def build_search_urls(templates, keywords) -> List[str]:
    """Turn search-URL *templates* (containing a ``{q}`` placeholder) + keywords into
    concrete search URLs. A template with no ``{q}`` is treated as a direct URL. This is
    what lets a study collect by keyword ("maggi") on a marketplace without pasting a URL
    per product — the URL varies, the template + keyword don't.
    """
    from urllib.parse import quote_plus

    urls: List[str] = []
    for tmpl in templates or []:
        tmpl = (tmpl or "").strip()
        if not tmpl:
            continue
        if "{q}" not in tmpl:
            urls.append(tmpl)
            continue
        for kw in keywords or []:
            kw = (kw or "").strip()
            if kw:
                urls.append(tmpl.replace("{q}", quote_plus(kw)))
    # De-dup, preserve order.
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> ScrapeResult:
    """params: urls (override), search_templates, keywords, proxy, timeout_ms, headless."""
    from scrapers.base import relevance_terms

    params = params or {}
    result = ScrapeResult(CHANNEL)
    sp = cfg.get("source_plan", {})

    # 1) Explicit product/category/search URLs (Source plan → E-commerce URLs).
    urls = list(params.get("urls") or sp.get("ecommerce_urls", []) or [])
    # 2) Keyword-driven: search-URL templates × keywords (URL varies, template doesn't).
    templates = params.get("search_templates") or sp.get("ecommerce_search", []) or []
    keywords = params.get("keywords") or sp.get("ecommerce_keywords") or relevance_terms(cfg)
    urls += build_search_urls(templates, keywords)
    # De-dup across both sources.
    seen, deduped = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u); deduped.append(u)
    urls = deduped

    if not urls:
        result.error("No e-commerce sources configured — add product/search URLs, or a search-URL "
                     "template with {q} plus keywords, in Source plan.")
        return result

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        result.error("Playwright is not installed. Run `playwright install chromium` (or use Docker). "
                     "E-commerce collection was skipped — no data fabricated.")
        return result

    proxy = params.get("proxy")
    timeout_ms = int(params.get("timeout_ms", 30000))
    headless = params.get("headless", True)

    try:
        with sync_playwright() as p:
            launch_kwargs: Dict[str, Any] = {"headless": headless}
            if proxy:
                launch_kwargs["proxy"] = {"server": proxy}
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context()

            for url in urls:
                captured_reviews: List[str] = []

                def _on_response(response, _bucket=captured_reviews):
                    try:
                        if looks_like_review_endpoint(response.url):
                            ctype = response.headers.get("content-type", "")
                            if "json" in ctype:
                                mine_review_json(response.json(), _bucket)
                    except Exception:
                        pass  # never let interception break the main crawl

                page = context.new_page()
                page.on("response", _on_response)
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)  # let review XHRs fire
                    title = page.title()
                    body_text = page.inner_text("body")
                    page_html = page.content()
                    images = page.eval_on_selector_all(
                        "img", "els => els.map(e => e.src).filter(Boolean)"
                    )
                    block = _looks_blocked(body_text, page_html)
                    if block["blocked"]:
                        result.error(f"E-commerce page appears blocked/unavailable ({url}): "
                                    f"{block['reason']}. Logged, not fabricated.")
                        continue

                    price = extract_price(body_text)

                    result.add(
                        {
                            "title": title or url,
                            "text": body_text[:20000],
                            "link": url,
                            "published": "",
                            "extra": {
                                "price": price,
                                "image_urls": images[:50],
                                "captured_review_count": len(captured_reviews),
                                "snapshot": True,
                            },
                        }
                    )
                    # Each intercepted review becomes its own item for analysis.
                    for i, rev in enumerate(captured_reviews):
                        result.add(
                            {
                                "title": f"Review ({title[:60]})",
                                "text": rev,
                                "link": url,
                                "published": "",
                                "extra": {"type": "review", "source_url": url, "review_index": i},
                            }
                        )
                except Exception as exc:
                    result.error(f"E-commerce page failed ({url}): {exc}")
                finally:
                    page.close()

            context.close()
            browser.close()
    except Exception as exc:
        result.error(f"Playwright session failed: {exc}")

    return result
