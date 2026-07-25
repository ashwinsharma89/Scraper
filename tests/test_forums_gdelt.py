"""Forum pagination (multi-language next labels) + GDELT metadata parsing."""
from scrapers import forums, gdelt


# --------------------------------------------------------------------------- #
# Forums
# --------------------------------------------------------------------------- #
PAGE1 = """<html><body>
  <div class="post">First user shares a detailed opinion about the product here.</div>
  <div class="post">Second user replies with more thoughts and a long comment.</div>
  <a href="/thread?page=2">下一页</a>
</body></html>"""

PAGE2 = """<html><body>
  <div class="post">Third user posts additional feedback on page two of the thread.</div>
  <span>no more pages</span>
</body></html>"""


def test_extract_posts_default_selector():
    posts = forums.extract_posts(PAGE1)
    assert len(posts) == 2
    assert "First user" in posts[0]["text"]


def test_find_next_link_chinese_label():
    labels = ["next", "下一页", "»"]
    nxt = forums.find_next_link(PAGE1, labels, "http://forum/thread")
    assert nxt == "http://forum/thread?page=2"


def test_collect_follows_pagination_with_cap():
    def fetch(url):
        class R:
            status_code = 200
            text = PAGE1 if url.endswith("/thread") else PAGE2
        return R()

    cfg = {
        "source_plan": {
            "forum_urls": ["http://forum/thread"],
            "forum_next_labels": {"zh": ["下一页"], "en": ["next"]},
        }
    }
    res = forums.collect(cfg, {"page_cap": 5}, fetch_fn=fetch)
    texts = " ".join(i["text"] for i in res.items)
    assert "First user" in texts and "Third user" in texts  # both pages crawled


# --------------------------------------------------------------------------- #
# GDELT
# --------------------------------------------------------------------------- #
def test_gdelt_build_query_scopes_country():
    q = gdelt.build_query(["Acme Cola", "Fizzly"], "SN")
    assert '"Acme Cola"' in q and "Fizzly" in q and "sourcecountry:SN" in q


def test_gdelt_parse_articles_metadata_only():
    payload = ('{"articles":[{"title":"Cola news","url":"http://x","seendate":"20240115T120000Z",'
               '"domain":"news.sg","language":"English","sourcecountry":"Singapore"}]}')
    items = gdelt.parse_articles(payload)
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "Cola news"
    assert it["published"] == "2024-01-15"
    assert it["text"] == ""  # metadata only, honestly empty
    assert it["extra"]["metadata_only"] is True


def test_gdelt_collect_requires_sourcecountry():
    cfg = {"relevance_terms": ["x"], "source_plan": {"gdelt": {"sourcecountry": ""}}}
    res = gdelt.collect(cfg, {}, fetch_fn=lambda u: None)
    assert res.items == []
    assert any("sourcecountry" in e for e in res.errors)
