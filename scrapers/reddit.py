"""Reddit collection via the public JSON endpoints (no API key).

  * Subreddits come from config.
  * Multi-sort union: new / top / relevance (search) / comments — deduped by post id.
  * Nested comment fetching for the top-N most-discussed posts.
  * Deleted / removed content is excluded.
  * 429s are handled gracefully: partial results are kept, the error is logged.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from scrapers.base import ScrapeResult, relevance_terms

CHANNEL = "reddit"
UA = {"User-Agent": "MarketLens/0.1 (research)"}

_DELETED_MARKERS = {"[deleted]", "[removed]", "", None}


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def is_deleted(comment_data: Dict[str, Any]) -> bool:
    body = comment_data.get("body")
    author = comment_data.get("author")
    if body in _DELETED_MARKERS:
        return True
    if author in _DELETED_MARKERS:
        return True
    return False


def walk_comments(children: List[Dict[str, Any]], depth: int = 0) -> List[Dict[str, Any]]:
    """Flatten a Reddit comment tree, EXCLUDING deleted/removed comments.

    ``children`` is the ``data.children`` list from a comments listing. Each child is
    ``{"kind": "t1", "data": {...}}``; replies are a nested listing or "". "more"
    stubs (kind == 'more') are skipped. A deleted comment is dropped entirely, but its
    non-deleted replies are still collected (promoted up), so we never lose real
    discussion just because a parent was removed.
    """
    out: List[Dict[str, Any]] = []
    for child in children or []:
        if child.get("kind") != "t1":
            continue  # skip 'more' stubs and anything non-comment
        data = child.get("data", {}) or {}
        replies = data.get("replies")
        reply_children = []
        if isinstance(replies, dict):
            reply_children = replies.get("data", {}).get("children", []) or []

        if not is_deleted(data):
            out.append(
                {
                    "id": data.get("id"),
                    "author": data.get("author"),
                    "body": data.get("body", ""),
                    "score": data.get("score", 0),
                    "depth": depth,
                    "created_utc": data.get("created_utc"),
                }
            )
        # Recurse regardless: real replies under a deleted parent still count.
        out.extend(walk_comments(reply_children, depth + 1))
    return out


def parse_listing_posts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract posts from a subreddit listing JSON."""
    out: List[Dict[str, Any]] = []
    for child in (payload or {}).get("data", {}).get("children", []) or []:
        if child.get("kind") != "t3":
            continue
        d = child.get("data", {}) or {}
        out.append(
            {
                "id": d.get("id"),
                "title": d.get("title", "") or "",
                "selftext": d.get("selftext", "") or "",
                "permalink": d.get("permalink", "") or "",
                "num_comments": d.get("num_comments", 0),
                "score": d.get("score", 0),
                "created_utc": d.get("created_utc"),
                "subreddit": d.get("subreddit", ""),
                "author": d.get("author", ""),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _default_fetch(url: str):
    from http_client import get_session

    return get_session().get(url, headers=UA)


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
            *, fetch_fn: Optional[Callable[[str], Any]] = None) -> ScrapeResult:
    """params: subreddits (override), top_n_comment_posts (default 5), published_after."""
    import json

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

    def _fetch_json(url):
        resp = fetch(url)
        status = getattr(resp, "status_code", 200)
        if status == 429:
            raise RuntimeError("HTTP 429 rate limited")
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
        text = getattr(resp, "text", "") or ""
        return json.loads(text)

    posts_by_id: Dict[str, Dict[str, Any]] = {}

    for sub in subs:
        sub = sub.strip().lstrip("r/").strip("/")
        sort_urls = [
            f"https://www.reddit.com/r/{sub}/new.json?limit=100",
            f"https://www.reddit.com/r/{sub}/top.json?limit=100&t=year",
            f"https://www.reddit.com/r/{sub}/comments.json?limit=100",
        ]
        from urllib.parse import quote_plus

        if query:
            sort_urls.append(
                f"https://www.reddit.com/r/{sub}/search.json?q={quote_plus(query)}"
                f"&restrict_sr=1&sort=relevance&limit=100"
            )
        for url in sort_urls:
            try:
                data = _fetch_json(url)
                for post in parse_listing_posts(data):
                    if post["id"] and post["id"] not in posts_by_id:
                        posts_by_id[post["id"]] = post
            except Exception as exc:
                # Graceful: keep whatever we already have, log the failure.
                result.error(f"Reddit listing failed (r/{sub}, {url.split('/')[-1]}): {exc}")

    # Emit posts as items.
    for post in posts_by_id.values():
        result.add(
            {
                "title": post["title"],
                "text": post["selftext"],
                "link": f"https://www.reddit.com{post['permalink']}" if post["permalink"] else "",
                "published": _epoch_iso(post.get("created_utc")),
                "extra": {"type": "post", "subreddit": post["subreddit"],
                          "score": post["score"], "num_comments": post["num_comments"]},
            }
        )

    # Comments for the top-N most-discussed posts.
    discussed = sorted(posts_by_id.values(), key=lambda p: p.get("num_comments", 0), reverse=True)[:top_n]
    for post in discussed:
        if not post.get("permalink"):
            continue
        url = f"https://www.reddit.com{post['permalink'].rstrip('/')}.json?limit=200"
        try:
            data = _fetch_json(url)
            if isinstance(data, list) and len(data) >= 2:
                children = data[1].get("data", {}).get("children", []) or []
                for c in walk_comments(children):
                    body = c.get("body", "")
                    if not body.strip():
                        continue
                    result.add(
                        {
                            "title": f"Comment on: {post['title'][:80]}",
                            "text": body,
                            "link": f"https://www.reddit.com{post['permalink']}",
                            "published": _epoch_iso(c.get("created_utc")),
                            "extra": {"type": "comment", "subreddit": post["subreddit"],
                                      "score": c.get("score", 0), "depth": c.get("depth", 0),
                                      "parent_post_id": post["id"]},
                        }
                    )
        except Exception as exc:
            result.error(f"Reddit comments failed ({post['permalink']}): {exc}")

    return result


def _epoch_iso(epoch) -> str:
    if not epoch:
        return ""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).date().isoformat()
    except (ValueError, OSError, TypeError):
        return ""
