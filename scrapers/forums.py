"""Forum collection (requests + BeautifulSoup).

User-supplied thread/listing URLs. Post containers are auto-detected from common forum
markup or overridden with a custom CSS selector. Pagination follows "next" links,
recognizing multi-language next-page labels (configured per project language). A page
cap prevents runaway crawls.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from scrapers.base import ScrapeResult

CHANNEL = "forums"

# Common forum post-container patterns, tried in order when no custom selector is set.
_DEFAULT_SELECTORS = [
    "article",
    "div.post",
    "div.message",
    "li.post",
    "div.comment",
    "div.forum-post",
    ".post-content",
    ".postbody",
    "[class*=post]",
    "[class*=message]",
]


def extract_posts(html: str, selector: Optional[str] = None) -> List[Dict[str, str]]:
    """Extract post text blocks from a forum page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    nodes = []
    if selector:
        nodes = soup.select(selector)
    else:
        for sel in _DEFAULT_SELECTORS:
            nodes = soup.select(sel)
            if nodes:
                break

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
