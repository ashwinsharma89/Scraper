"""Quora collection (best-effort).

Quora is hostile to automation. We attempt question-page scraping with the SAME strict
relevance validation used for news; if a page is blocked or returns a login wall, we
log it honestly and move on — we never fabricate answers.

Verified live: Quora sits behind Cloudflare's managed bot-challenge (a "Just a
moment..." JS-challenge interstitial, HTTP 403) on every request, regardless of
User-Agent — confirmed universal across multiple real question URLs. This is
fundamentally different from (and harder than) a simple header/rate-limit block: it
requires executing JavaScript in a real browser to solve, which plain requests +
BeautifulSoup cannot do. This is NOT something to "fix" by faking a browser — that
would mean either running a full headless browser per request (a much heavier,
fragile approach explicitly out of scope for a lightweight requests-based channel) or
defeating an anti-bot system, which this tool does not do. The honest behavior is what
is implemented here: detect the challenge specifically, report it precisely, never
fabricate a result.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from scrapers import relevance
from scrapers.base import ScrapeResult, relevance_terms

CHANNEL = "quora"

# Markers confirmed live in Quora's actual Cloudflare challenge page.
_CLOUDFLARE_MARKERS = ["_cf_chl_opt", "cdn-cgi/challenge-platform", "just a moment",
                       "challenges.cloudflare.com", "cf-browser-verification"]


def _default_fetch(url: str):
    from http_client import get_session

    return get_session().get(url)


def _cloudflare_challenge(html: str) -> bool:
    low = (html or "").lower()
    return any(marker in low for marker in _CLOUDFLARE_MARKERS)


def _looks_blocked(html: str) -> bool:
    low = (html or "").lower()
    return _cloudflare_challenge(html) or \
           ("log in" in low and "sign up" in low and "quora" in low and len(low) < 4000) or \
           "captcha" in low or "unusual traffic" in low


def _block_reason(status: int, html: str) -> str:
    """A specific, diagnostic reason instead of a generic 'likely blocked' — this is
    what actually happened, so anyone debugging later doesn't have to rediscover it."""
    if _cloudflare_challenge(html):
        return (f"HTTP {status}, Cloudflare bot-challenge ('Just a moment...' JS "
                f"challenge) — requires executing JavaScript to solve; not fixable "
                f"without a real browser. Logged, not fabricated.")
    if "captcha" in (html or "").lower():
        return f"HTTP {status}, CAPTCHA wall. Logged, not fabricated."
    if "log in" in (html or "").lower() and "sign up" in (html or "").lower():
        return f"HTTP {status}, login/signup wall. Logged, not fabricated."
    return f"HTTP {status} (likely blocked). Logged, not fabricated."


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
            *, fetch_fn: Optional[Callable[[str], Any]] = None) -> ScrapeResult:
    params = params or {}
    fetch = fetch_fn or _default_fetch
    result = ScrapeResult(CHANNEL)

    urls: List[str] = params.get("urls") or cfg.get("source_plan", {}).get("quora_topics", [])
    if not urls:
        result.error("No Quora question URLs configured.")
        return result

    terms = relevance_terms(cfg)
    for url in urls:
        try:
            resp = fetch(url)
            status = getattr(resp, "status_code", 200)
            html = getattr(resp, "text", "") or ""
            # Read the body (when there is one) before deciding the message, so a
            # 403 that's actually a Cloudflare challenge gets reported as exactly
            # that instead of a generic "likely blocked".
            if status >= 400 or _looks_blocked(html):
                result.error(f"Quora {url} -> {_block_reason(status, html)}")
                continue

            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            title = (soup.find("title").get_text(strip=True) if soup.find("title") else url)
            body = relevance.extract_main_text(html)
            verdict = relevance.validate_relevance(title, terms, html)
            if not verdict["relevant"]:
                continue
            result.add(
                {
                    "title": title,
                    "text": verdict["text"] or body,
                    "link": url,
                    "published": "",
                    "extra": {"type": "quora_question", "matched_in": verdict["matched_in"]},
                }
            )
        except Exception as exc:
            result.error(f"Quora fetch failed ({url}): {exc}")
    return result
