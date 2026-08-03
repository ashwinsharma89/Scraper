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


# A realistic IPB-family (e.g. Lowyat.net) fixture: the real content lives in
# ".postcolor", but a wrapper div with "post" in its class also wraps a bunch of short
# chrome fragments (timestamps, "show posts by member", profile bio) that a naive
# "first selector matching anything" approach would latch onto instead. This is the
# exact real bug caught live against forum.lowyat.net during this fix.
REAL_FORUM_PAGE = """<html><body>
  <div class="postwrap">
    <div class="postheader">TS lidesigns Mar 22 2026, 08:41 PM Show posts by this member only</div>
    <div class="postprofile">New Member Probation 5 posts Joined: May 2022 From: Kuala Lumpur</div>
    <div class="postcolor">I have been using this product for months and the quality has really
      dropped compared to last year, especially the packaging which feels much cheaper now.</div>
  </div>
  <div class="postwrap">
    <div class="postheader">Reply #1 Mar 23 2026, 09:00 AM Show posts by this member only</div>
    <div class="postprofile">Senior Member 1200 posts Joined: Jan 2019</div>
    <div class="postcolor">Totally agree, I noticed the same thing when I bought a pack last week
      at the supermarket near my house, tasted different too.</div>
  </div>
</body></html>"""


def test_scored_selector_prefers_real_content_over_chrome_wildcard():
    """Structural fix: the wildcard [class*=post] matches BOTH real content AND chrome
    (more numerous but short); scoring by average substantial-match length correctly
    picks .postcolor (real posts) over the wildcard's chrome-diluted average."""
    posts = forums.extract_posts(REAL_FORUM_PAGE)
    assert len(posts) == 2
    texts = " ".join(p["text"] for p in posts)
    assert "quality has really" in texts and "tasted different too" in texts
    # Chrome must NOT be what got extracted.
    assert "Show posts by this member only" not in texts
    assert "New Member Probation" not in texts


def test_broad_fallback_still_works_when_no_specific_selector_matches():
    """Software using neither a known specific class nor .postcolor still gets SOME
    extraction via the broad fallback list — verifies the two-tier design end-to-end."""
    posts = forums.extract_posts(PAGE1)  # uses div.post, not in the specific list
    assert len(posts) == 2
    assert "First user" in posts[0]["text"]


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


def test_gdelt_drops_items_whose_title_matches_no_relevance_term():
    """GDELT server-side matching is loose; the collector must re-check the title so
    Malaysia-sourced-but-irrelevant news (e.g. foldable phones) is dropped."""
    payload = ('{"articles":['
               '{"title":"Maggi price rises in KL","url":"http://a","seendate":"20260115T120000Z","domain":"nst.com.my"},'
               '{"title":"Foldable phones get pricier this year","url":"http://b","seendate":"20260115T120000Z","domain":"x.my"}'
               ']}')

    class R:
        status_code = 200
        text = payload

    cfg = {"relevance_terms": ["Maggi"], "source_plan": {"gdelt": {"sourcecountry": "MY"}},
           "collection_settings": {}}
    res = gdelt.collect(cfg, {"start_date": "2026-01-01", "end_date": "2026-01-31"}, fetch_fn=lambda u: R())
    assert [i["title"] for i in res.items] == ["Maggi price rises in KL"]  # noise dropped
    assert res.diagnostics.get("irrelevant_dropped") == 1
