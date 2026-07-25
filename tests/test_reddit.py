"""Reddit comment-tree walk excludes deleted/removed; listing parse; graceful 429."""
import json

from scrapers import reddit


# A nested comment tree: some deleted, some removed, real replies under a deleted parent.
COMMENTS = [
    {"kind": "t1", "data": {
        "id": "c1", "author": "alice", "body": "Great product overall", "score": 10,
        "replies": {"data": {"children": [
            {"kind": "t1", "data": {"id": "c1a", "author": "[deleted]", "body": "[deleted]",
                                     "replies": ""}},
            {"kind": "t1", "data": {"id": "c1b", "author": "bob", "body": "Agree, tastes good",
                                     "replies": ""}},
        ]}},
    }},
    {"kind": "t1", "data": {
        "id": "c2", "author": "carol", "body": "[removed]",
        "replies": {"data": {"children": [
            {"kind": "t1", "data": {"id": "c2a", "author": "dan", "body": "Reply survives removal",
                                     "replies": ""}},
        ]}},
    }},
    {"kind": "more", "data": {"id": "more1", "children": ["x", "y"]}},
]


def test_walk_comments_excludes_deleted_keeps_real_replies():
    flat = reddit.walk_comments(COMMENTS)
    bodies = [c["body"] for c in flat]
    assert "Great product overall" in bodies
    assert "Agree, tastes good" in bodies
    # Deleted and removed comment bodies are gone.
    assert "[deleted]" not in bodies
    assert "[removed]" not in bodies
    # A real reply nested under a REMOVED parent still survives.
    assert "Reply survives removal" in bodies
    # 'more' stubs never produce items.
    assert len(flat) == 3


def test_is_deleted():
    assert reddit.is_deleted({"body": "[deleted]", "author": "x"}) is True
    assert reddit.is_deleted({"body": "text", "author": "[deleted]"}) is True
    assert reddit.is_deleted({"body": "text", "author": "real"}) is False


def test_parse_listing_posts():
    payload = {"data": {"children": [
        {"kind": "t3", "data": {"id": "p1", "title": "Post one", "selftext": "body",
                                 "permalink": "/r/x/p1", "num_comments": 5, "score": 3,
                                 "subreddit": "x"}},
        {"kind": "t3", "data": {"id": "p2", "title": "Post two", "permalink": "/r/x/p2",
                                 "num_comments": 20, "subreddit": "x"}},
    ]}}
    posts = reddit.parse_listing_posts(payload)
    assert [p["id"] for p in posts] == ["p1", "p2"]
    assert posts[1]["num_comments"] == 20


class _Resp:
    def __init__(self, text="", status=200):
        self.text = text
        self.status_code = status


def test_collect_graceful_429_keeps_partial():
    listing = json.dumps({"data": {"children": [
        {"kind": "t3", "data": {"id": "p1", "title": "Acme Cola review", "selftext": "tasty",
                                 "permalink": "/r/food/p1", "num_comments": 2, "subreddit": "food"}},
    ]}})

    calls = {"n": 0}

    def fetch(url, **kwargs):
        calls["n"] += 1
        # First listing succeeds; a later sort returns 429.
        if "new.json" in url:
            return _Resp(listing)
        if "top.json" in url:
            return _Resp("", status=429)
        if url.endswith("p1.json?limit=200") or "/p1.json" in url:
            return _Resp(json.dumps([{}, {"data": {"children": COMMENTS}}]))
        return _Resp(json.dumps({"data": {"children": []}}))

    cfg = {"relevance_terms": ["Acme Cola"], "source_plan": {"subreddits": ["food"]}}
    res = reddit.collect(cfg, {"top_n_comment_posts": 1}, fetch_fn=fetch)
    # Post from the successful sort is kept despite the 429 on another sort.
    titles = [i["title"] for i in res.items]
    assert "Acme Cola review" in titles
    # The 429 was logged, not swallowed.
    assert any("429" in e for e in res.errors)
    # Comments were collected for the discussed post (deleted excluded).
    assert any(i["extra"].get("type") == "comment" for i in res.items)
