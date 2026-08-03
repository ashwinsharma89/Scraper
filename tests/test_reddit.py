"""Reddit RSS parsing: post/comment extraction, deleted-exclusion, graceful 429.

The old .json API is blocked by Reddit outright (verified live: 403 from Reddit's own
edge, not fixable). .rss (Atom) feeds still work for unauthenticated access — this
module was rewritten around them. Real endpoint shapes and rate-limit behavior were
confirmed live against r/malaysia before writing these fixtures.
"""
import pytest

from scrapers import reddit


@pytest.fixture(autouse=True)
def _no_real_sleeps(monkeypatch):
    # The module's 429 retry deliberately waits ~20s against the real Reddit API;
    # tests must not actually sleep for that.
    monkeypatch.setattr(reddit, "RETRY_429_WAIT", 0)

# A real-shaped Atom listing: first entry is a post, offset by other tags.
LISTING_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <author><name>/u/alice</name></author>
  <id>t3_abc123</id>
  <link href="https://www.reddit.com/r/malaysia/comments/abc123/maggi_price_hike/" />
  <title>Maggi price hike noticed at Tesco</title>
  <published>2026-03-01T12:00:00+00:00</published>
</entry>
<entry>
  <author><name>/u/bob</name></author>
  <id>t3_def456</id>
  <link href="https://www.reddit.com/r/malaysia/comments/def456/unrelated/" />
  <title>Unrelated weather post</title>
  <published>2026-03-02T12:00:00+00:00</published>
</entry>
</feed>"""

# A real-shaped comments feed: entry 0 = the post itself (t3_), rest are comments (t1_),
# including a deleted comment and a real reply nested "under" it (RSS is flat, no true
# nesting, but the reply must still survive being adjacent to a deleted comment).
COMMENTS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <author><name>/u/alice</name></author>
  <id>t3_abc123</id>
  <title>Maggi price hike noticed at Tesco</title>
  <content type="html">post body blob</content>
</entry>
<entry>
  <author><name>/u/carol</name></author>
  <id>t1_c1</id>
  <title>/u/carol on Maggi price hike noticed at Tesco</title>
  <content type="html">&lt;div class="md"&gt;&lt;p&gt;Noticed the same thing at Giant too.&lt;/p&gt;&lt;/div&gt;</content>
  <published>2026-03-01T13:00:00+00:00</published>
</entry>
<entry>
  <author><name>[deleted]</name></author>
  <id>t1_c2</id>
  <title>/u/[deleted] on Maggi price hike noticed at Tesco</title>
  <content type="html">&lt;div class="md"&gt;&lt;p&gt;[deleted]&lt;/p&gt;&lt;/div&gt;</content>
  <published>2026-03-01T14:00:00+00:00</published>
</entry>
<entry>
  <author><name>/u/dave</name></author>
  <id>t1_c3</id>
  <title>/u/dave on Maggi price hike noticed at Tesco</title>
  <content type="html">&lt;div class="md"&gt;&lt;p&gt;Prices are up everywhere honestly.&lt;/p&gt;&lt;/div&gt;</content>
  <published>2026-03-01T15:00:00+00:00</published>
</entry>
</feed>"""


class _Resp:
    def __init__(self, content=b"", status=200):
        self.content = content
        self.status_code = status


# --------------------------------------------------------------------------- #
# Pure parsing
# --------------------------------------------------------------------------- #
def test_parse_rss_posts_extracts_only_post_entries():
    posts = reddit.parse_rss_posts(LISTING_XML)
    assert len(posts) == 2
    assert posts[0]["id"] == "t3_abc123"
    assert posts[0]["title"] == "Maggi price hike noticed at Tesco"
    assert posts[0]["author"] == "alice"
    assert posts[0]["published"] == "2026-03-01"


def test_parse_rss_comments_excludes_deleted_keeps_real_replies():
    comments = reddit.parse_rss_comments(COMMENTS_XML)
    bodies = [c["body"] for c in comments]
    # Post itself (t3_) is not treated as a comment.
    assert not any("post body blob" in b for b in bodies)
    # Real comments kept.
    assert any("Noticed the same thing at Giant" in b for b in bodies)
    assert any("Prices are up everywhere" in b for b in bodies)
    # Deleted comment excluded entirely.
    assert not any("[deleted]" in b for b in bodies)
    assert len(comments) == 2


def test_is_deleted():
    assert reddit.is_deleted("[deleted]", "some text") is True
    assert reddit.is_deleted("real_author", "[removed]") is True
    assert reddit.is_deleted("real_author", "real comment text") is False
    assert reddit.is_deleted(None, None) is True


# --------------------------------------------------------------------------- #
# End-to-end collect()
# --------------------------------------------------------------------------- #
def _cfg():
    return {"relevance_terms": ["Maggi"], "source_plan": {"subreddits": ["malaysia"]}}


def test_collect_dedupes_across_new_and_top_and_fetches_comments():
    calls = []

    def fetch(url):
        calls.append(url)
        if "search.rss" in url:
            return _Resp(LISTING_XML)  # same posts, different sort -> must dedupe
        if "new.rss" in url or "top.rss" in url:
            return _Resp(LISTING_XML)
        if ".rss" in url and "/comments/abc123/" in url:
            return _Resp(COMMENTS_XML)
        if ".rss" in url and "/comments/def456/" in url:
            return _Resp(b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        return _Resp(b"", status=404)

    res = reddit.collect(_cfg(), {"top_n_comment_posts": 2}, fetch_fn=fetch)
    posts = [i for i in res.items if i["extra"]["type"] == "post"]
    comments = [i for i in res.items if i["extra"]["type"] == "comment"]

    # Deduped: 2 unique posts even though new/top/search all returned the same two.
    assert len(posts) == 2
    assert {p["title"] for p in posts} == {"Maggi price hike noticed at Tesco", "Unrelated weather post"}
    # Comments fetched and deleted-filtered.
    assert len(comments) == 2
    assert all(c["extra"]["depth"] == 0 for c in comments)  # RSS is flat, honestly labeled


def test_collect_requires_subreddits():
    res = reddit.collect({"relevance_terms": [], "source_plan": {}}, {}, fetch_fn=lambda u: _Resp())
    assert res.items == []
    assert any("No subreddits" in e for e in res.errors)


def test_collect_graceful_429_keeps_partial_listing_results():
    def fetch(url):
        if "new.rss" in url:
            return _Resp(LISTING_XML)
        if "top.rss" in url:
            return _Resp(b"", status=429)
        if "search.rss" in url:
            return _Resp(b"", status=429)
        return _Resp(b"", status=404)  # comment fetches also fail -> no comments, that's fine

    res = reddit.collect(_cfg(), {"top_n_comment_posts": 0}, fetch_fn=fetch)
    titles = [i["title"] for i in res.items]
    # new.rss succeeded -> its posts are kept despite top/search being rate-limited.
    assert "Maggi price hike noticed at Tesco" in titles
    assert any("429" in e for e in res.errors)


def test_collect_comment_fetch_429_is_logged_not_fatal():
    def fetch(url):
        if "new.rss" in url:
            return _Resp(LISTING_XML)
        if "top.rss" in url or "search.rss" in url:
            return _Resp(b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        if ".rss" in url and "/comments/" in url:
            return _Resp(b"", status=429)
        return _Resp(b"", status=404)

    res = reddit.collect(_cfg(), {"top_n_comment_posts": 5}, fetch_fn=fetch)
    posts = [i for i in res.items if i["extra"]["type"] == "post"]
    assert len(posts) == 2  # listings still succeeded
    assert any("429" in e or "rate-limited" in e for e in res.errors)
