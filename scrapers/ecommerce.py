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


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> ScrapeResult:
    """params: urls (override), proxy (per-run), timeout_ms, headless."""
    params = params or {}
    result = ScrapeResult(CHANNEL)

    urls = params.get("urls") or cfg.get("source_plan", {}).get("ecommerce_urls", [])
    if not urls:
        result.error("No e-commerce URLs configured — add product/category/search URLs.")
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
                    images = page.eval_on_selector_all(
                        "img", "els => els.map(e => e.src).filter(Boolean)"
                    )
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
