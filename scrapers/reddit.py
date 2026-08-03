"""Reddit collection via public Atom/RSS feeds (no API key).

As of Reddit's 2023 anti-scraping crackdown, the legacy unauthenticated `.json`
endpoints are blocked outright — verified live: a consistent `403` straight from
Reddit's own edge servers (`snooserv`), not a generic proxy/Cloudflare challenge, and
not fixable by changing the User-Agent or the requesting IP's reverse-DNS. The legacy
`.rss` (Atom) feeds, however, still work for unauthenticated access — also verified
live against r/malaysia, including real consumer content a News/GDELT channel
structurally cannot surface (e.g. genuine posts and comments about a product).

Two real, honest capability reductions versus the old JSON API, both because RSS is a
much thinner data format than JSON — documented rather than silently worked around:
  * RSS listings expose NO comment-count field, so "top-N most-discussed posts" can no
    longer be ranked by comment count. We rank by whatever order the listing itself
    returns (new/top are already Reddit's own ranking) and fetch comments for the
    first N found instead.
  * RSS comment feeds are FLAT — no parent/depth/reply-threading metadata at all.
    ``depth`` is always 0. Deleted/removed comments are still detected and excluded
    (via author/body markers), just without tree structure.

Rate limit is tight — tighter than a typical read API — confirmed live: back-to-back
requests reliably 429, recovering after ~15-20s. This module paces itself accordingly
(a per-call ``rate_delay`` override, well above the tool's global default) rather than
hammering and relying on retries alone.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote_plus

from scrapers.base import ScrapeResult, relevance_terms

CHANNEL = "reddit"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
# Reddit's RSS rate limit is materially tighter than this tool's global default
# (verified live: sub-5s spacing reliably 429s). Pace every Reddit request at this
# floor. http_client's global retry-on-429 uses a short backoff (fine for APIs with a
# normal limit); Reddit's real cooldown was observed live to need ~15-25s, well beyond
# that — so this module adds its OWN longer wait-and-retry for 429s specifically,
# scoped here rather than loosening the global policy for every other channel.
RATE_DELAY = 6.0
RETRY_429_WAIT = 20.0
RETRY_429_ATTEMPTS = 2

_DELETED_MARKERS = {"[deleted]", "[removed]", "", None}


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def is_deleted(author: Optional[str], body: Optional[str]) -> bool:
    a = (author or "").strip()
    b = (body or "").strip()
    return a in _DELETED_MARKERS or b in _DELETED_MARKERS or b in {"[deleted]", "[removed]"}


def _strip_html(html: str) -> str:
    from bs4 import BeautifulSoup

    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def parse_rss_posts(raw: bytes) -> List[Dict[str, Any]]:
    """Parse a subreddit listing feed (new.rss / top.rss / search.rss) into posts.

    feedparser MUST receive raw bytes, not a pre-decoded string — Reddit's Atom feed
    declares its own encoding, and feeding feedparser an already-decoded ``str`` causes
    a silent parse failure (0 entries) on some responses. This was a real bug caught
    live during this fix.
    """
    import feedparser

    parsed = feedparser.parse(raw)
    out: List[Dict[str, Any]] = []
    for e in parsed.entries:
        post_id = (e.get("id") or "").strip()
        if not post_id.startswith("t3_"):
            continue
        out.append(
            {
                "id": post_id,
                "title": e.get("title", "") or "",
                "link": e.get("link", "") or "",
                "author": (e.get("author", "") or "").replace("/u/", "").strip(),
                "published": (e.get("published", "") or "")[:10],
            }
        )
    return out


def parse_rss_comments(raw: bytes) -> List[Dict[str, Any]]:
    """Parse a post's comments feed (``{permalink}.rss``).

    The first entry is always the post itself (id starts with ``t3_``) — skipped.
    Remaining entries (``t1_``) are comments, in whatever order Reddit returns (flat,
    no depth). Deleted/removed comments are excluded here, not left for the caller.
    """
    import feedparser

    parsed = feedparser.parse(raw)
    out: List[Dict[str, Any]] = []
    for e in parsed.entries:
        cid = (e.get("id") or "").strip()
        if not cid.startswith("t1_"):
            continue
        author = (e.get("author", "") or "").replace("/u/", "").strip()
        content = e.get("content", [{}])
        body_html = content[0].get("value", "") if content else e.get("summary", "")
        body = _strip_html(body_html)
        if is_deleted(author, body):
            continue
        out.append(
            {
                "id": cid,
                "author": author,
                "body": body,
                "published": (e.get("published", "") or "")[:10],
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _default_fetch(url: str):
    from http_client import get_session

    return get_session().get(url, headers=UA, rate_delay=RATE_DELAY)


def _fetch_with_429_retry(fetch: Callable[[str], Any], url: str,
                          wait: Optional[float] = None, attempts: Optional[int] = None):
    """Call fetch(url); on HTTP 429, sleep and retry (Reddit-specific — see module
    docstring). Returns the last response regardless of outcome; the caller checks
    status_code as usual, so a persistent 429 still surfaces as an honest error.

    wait/attempts default to the module constants, resolved at CALL time (not as
    default-argument values) so tests can monkeypatch RETRY_429_WAIT/RETRY_429_ATTEMPTS
    on the module and have it actually take effect — Python binds default argument
    values once at function-definition time, so `wait: float = RETRY_429_WAIT` would
    silently ignore a later `monkeypatch.setattr(reddit, "RETRY_429_WAIT", 0)`.
    """
    if wait is None:
        wait = RETRY_429_WAIT
    if attempts is None:
        attempts = RETRY_429_ATTEMPTS
    resp = fetch(url)
    tries = 0
    while getattr(resp, "status_code", 200) == 429 and tries < attempts:
        time.sleep(wait)
        resp = fetch(url)
        tries += 1
    return resp


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
            *, fetch_fn: Optional[Callable[[str], Any]] = None) -> ScrapeResult:
    """params: subreddits (override), top_n_comment_posts (default 5)."""
    params = params or {}
    fetch = fetch_fn or _default_fetch
    result = ScrapeResult(CHANNEL)

    subs = params.get("subreddits") or cfg.get("source_plan", {}).get("subreddits", [])
    if not subs:
        result.error("No subreddits configured — confirm subreddit candidates in the source plan.")
        return result

    terms = relevance_terms(cfg)
    top_n = int(params.get("top_n_comment_posts", 5))
    query = " OR ".join(f'"{t}"' if " " in t else t for t in terms) if terms else ""

    def _fetch_posts(url: str) -> List[Dict[str, Any]]:
        resp = _fetch_with_429_retry(fetch, url)
        status = getattr(resp, "status_code", 200)
        if status == 429:
            raise RuntimeError("HTTP 429 rate limited")
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
        return parse_rss_posts(getattr(resp, "content", b"") or b"")

    posts_by_id: Dict[str, Dict[str, Any]] = {}

    for sub in subs:
        sub = sub.strip().lstrip("r/").strip("/")
        urls = [
            f"https://www.reddit.com/r/{sub}/new.rss",
            f"https://www.reddit.com/r/{sub}/top.rss?t=year",
        ]
        if query:
            urls.append(f"https://www.reddit.com/r/{sub}/search.rss?q={quote_plus(query)}"
                       f"&restrict_sr=1&sort=relevance")
        for url in urls:
            try:
                for post in _fetch_posts(url):
                    if post["id"] not in posts_by_id:
                        posts_by_id[post["id"]] = {**post, "subreddit": sub}
            except Exception as exc:
                # Graceful: keep whatever we already have, log the failure.
                result.error(f"Reddit listing failed (r/{sub}, {url.split('/')[-1][:40]}): {exc}")

    for post in posts_by_id.values():
        result.add(
            {
                "title": post["title"],
                "text": "",  # RSS listings carry no post selftext, only a link/thumbnail blob
                "link": post["link"],
                "published": post["published"],
                "extra": {"type": "post", "subreddit": post["subreddit"], "author": post["author"]},
            }
        )

    # Comments for the first N posts found (RSS exposes no comment-count to rank by —
    # an honest reduction from the old JSON API's num_comments-based "most discussed").
    for post in list(posts_by_id.values())[:top_n]:
        if not post.get("link"):
            continue
        url = post["link"].rstrip("/") + "/.rss"
        try:
            resp = _fetch_with_429_retry(fetch, url)
            status = getattr(resp, "status_code", 200)
            if status == 429:
                result.error(f"Reddit comments rate-limited ({post['link']}): HTTP 429")
                continue
            if status >= 400:
                result.error(f"Reddit comments failed ({post['link']}): HTTP {status}")
                continue
            for c in parse_rss_comments(getattr(resp, "content", b"") or b""):
                if not c["body"]:
                    continue
                result.add(
                    {
                        "title": f"Comment on: {post['title'][:80]}",
                        "text": c["body"],
                        "link": post["link"],
                        "published": c["published"],
                        "extra": {"type": "comment", "subreddit": post["subreddit"],
                                  "author": c["author"], "depth": 0,  # RSS is flat — no tree
                                  "parent_post_id": post["id"]},
                    }
                )
        except Exception as exc:
            result.error(f"Reddit comments failed ({post['link']}): {exc}")

    return result
