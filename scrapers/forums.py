"""Forum collection (requests + BeautifulSoup).

User-supplied thread/listing URLs. Post containers are auto-detected from common forum
markup or overridden with a custom CSS selector. Pagination follows "next" links,
recognizing multi-language next-page labels (configured per project language). A page
cap prevents runaway crawls.

Selector picking is SCORED, not first-match-wins. Verified live against a real modern
IPB-family forum thread (Lowyat.net): a naive "first selector that matches anything"
approach picks a broad wildcard like ``[class*=post]`` — which matches real post bodies
AND unrelated chrome (post-header timestamps, "Show posts by this member only",
profile/rank sidebars) that also happen to have "post" in their class name. The chrome
matches are numerous but short/diluting; real post content is comparatively rare but
consistently long. So candidates are scored by the AVERAGE length of their substantial
(>=40 char) matches, not by match count — this reliably prefers a specific selector
like ``.postcolor`` (IPB/IP.Board's actual message-body class, avg ~400 chars/match)
over a wildcard catching mostly chrome (avg ~200 chars/match) even though the wildcard
has far more raw matches.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from scrapers.base import ScrapeResult

CHANNEL = "forums"

# Specific, high-confidence post-body classes from major forum platforms, tried first.
_SPECIFIC_SELECTORS = [
    ".postcolor",       # IPB / IP.Board (e.g. Lowyat.net) — verified live
    ".post_body",
    ".postbody",
    ".post-content",
    ".message-content",
    ".post-message",
    ".postmessage",
    ".bbp-reply-content",  # bbPress
    ".message-body",       # XenForo
]
# Broader, riskier fallbacks — only consulted if none of the above matched anything.
_BROAD_SELECTORS = [
    "article",
    "div.post",
    "div.message",
    "li.post",
    "div.comment",
    "div.forum-post",
    "[class*=post]",
    "[class*=message]",
]
_SUBSTANTIAL_MIN_LEN = 40  # below this, a match is more likely chrome than real content


def _score_selector(soup, selector: str) -> Optional[Dict[str, Any]]:
    """Return {"nodes": [...], "score": avg_len} for substantial matches, or None."""
    nodes = soup.select(selector)
    substantial = [n for n in nodes if len(n.get_text(" ", strip=True)) >= _SUBSTANTIAL_MIN_LEN]
    if not substantial:
        return None
    avg_len = sum(len(n.get_text(" ", strip=True)) for n in substantial) / len(substantial)
    return {"nodes": substantial, "score": avg_len}


def extract_posts(html: str, selector: Optional[str] = None) -> List[Dict[str, str]]:
    """Extract post text blocks from a forum page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    nodes: List[Any] = []
    if selector:
        nodes = soup.select(selector)
    else:
        candidates = []
        for sel in _SPECIFIC_SELECTORS:
            result = _score_selector(soup, sel)
            if result:
                candidates.append(result)
        if not candidates:
            # No high-confidence selector matched anything — fall back to the broad
            # (riskier) list, still scored the same way rather than first-match-wins.
            for sel in _BROAD_SELECTORS:
                result = _score_selector(soup, sel)
                if result:
                    candidates.append(result)
        if candidates:
            best = max(candidates, key=lambda c: c["score"])
            nodes = best["nodes"]

    posts: List[Dict[str, str]] = []
    for i, node in enumerate(nodes):
        text = node.get_text(" ", strip=True)
        if len(text) < 15:  # skip empty/nav-like containers
            continue
        posts.append({"text": text, "index": str(i)})
    return posts


def find_next_link(html: str, labels: List[str], base_url: str) -> Optional[str]:
    """Return the absolute URL of the 'next page' link, matching any configured label."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    lowered_labels = [l.strip().lower() for l in labels if l.strip()]

    # Prefer rel="next".
    rel_next = soup.find("a", rel="next")
    if rel_next and rel_next.get("href"):
        return urljoin(base_url, rel_next["href"])

    for a in soup.find_all("a"):
        label = a.get_text(" ", strip=True).lower()
        aria = (a.get("aria-label", "") or "").lower()
        title = (a.get("title", "") or "").lower()
        candidates = {label, aria, title}
        if any(lbl in candidates or lbl in label for lbl in lowered_labels):
            if a.get("href"):
                return urljoin(base_url, a["href"])
    return None


def _default_fetch(url: str):
    from http_client import get_session

    return get_session().get(url)


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
            *, fetch_fn: Optional[Callable[[str], Any]] = None) -> ScrapeResult:
    """params: forum_urls (override), selector (custom CSS), page_cap."""
    params = params or {}
    fetch = fetch_fn or _default_fetch
    result = ScrapeResult(CHANNEL)

    urls = params.get("forum_urls") or cfg.get("source_plan", {}).get("forum_urls", [])
    if not urls:
        result.error("No forum URLs configured — add thread/listing URLs to the source plan.")
        return result

    selector = params.get("selector")
    page_cap = int(params.get("page_cap", cfg.get("collection_settings", {}).get("forum_page_cap", 10)))

    # Build the multi-language next-label list from the project config.
    label_map = cfg.get("source_plan", {}).get("forum_next_labels", {})
    labels: List[str] = []
    for lang_labels in label_map.values():
        labels.extend(lang_labels)
    if not labels:
        labels = ["next", "»", ">"]

    for start_url in urls:
        current = start_url
        pages = 0
        visited = set()
        while current and pages < page_cap and current not in visited:
            visited.add(current)
            pages += 1
            try:
                resp = fetch(current)
                if getattr(resp, "status_code", 200) >= 400:
                    result.error(f"Forum page {current} -> HTTP {resp.status_code}")
                    break
                html = getattr(resp, "text", "") or ""
            except Exception as exc:
                result.error(f"Forum fetch failed ({current}): {exc}")
                break

            for post in extract_posts(html, selector):
                result.add(
                    {
                        "title": f"Forum post ({start_url})",
                        "text": post["text"],
                        "link": current,
                        "published": "",
                        "extra": {"thread": start_url, "page": pages, "post_index": post["index"]},
                    }
                )
            current = find_next_link(html, labels, current)

    return result
