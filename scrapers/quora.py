"""Quora collection (best-effort).

Quora is hostile to automation. We attempt question-page scraping with the SAME strict
relevance validation used for news; if a page is blocked or returns a login wall, we
log it honestly and move on — we never fabricate answers.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from scrapers import relevance
from scrapers.base import ScrapeResult, relevance_terms

CHANNEL = "quora"


def _default_fetch(url: str):
    from http_client import get_session

    return get_session().get(url)


def _looks_blocked(html: str) -> bool:
    low = (html or "").lower()
    return ("log in" in low and "sign up" in low and "quora" in low and len(low) < 4000) or \
           "captcha" in low or "unusual traffic" in low


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
            if status >= 400:
                result.error(f"Quora {url} -> HTTP {status} (likely blocked; logged, not fabricated).")
                continue
            html = getattr(resp, "text", "") or ""
            if _looks_blocked(html):
                result.error(f"Quora {url} returned a login/CAPTCHA wall — blocked, logged honestly.")
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
