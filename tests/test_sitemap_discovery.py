"""Sitemap-based URL discovery (DESIGN_01_category-discovery.md §4 tier 2)."""
import sitemap_discovery as sd


class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


SITEMAP_INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap_2026-09-13.xml</loc><lastmod>2026-09-13</lastmod></sitemap>
  <sitemap><loc>https://example.com/sitemap_2026-09-12.xml</loc><lastmod>2026-09-12</lastmod></sitemap>
  <sitemap><loc>https://example.com/sitemap_2026-09-11.xml</loc><lastmod>2026-09-11</lastmod></sitemap>
</sitemapindex>"""

SUB_SITEMAP_1 = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/coffee/best-cafes-bangalore</loc><lastmod>2026-09-13</lastmod></url>
  <url><loc>https://example.com/politics/election-update</loc><lastmod>2026-09-13</lastmod></url>
</urlset>"""

SUB_SITEMAP_2 = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/lifestyle/coffee-culture-mumbai</loc><lastmod>2026-09-12</lastmod></url>
</urlset>"""

PLAIN_URLSET = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc></url>
  <url><loc>https://example.com/b</loc></url>
</urlset>"""

# The exact real shape found live (Increment 9, thanhnien.vn/vietnamnet.vn): category
# and utility sub-sitemaps (no lastmod) listed BEFORE the actual dated article
# sub-sitemaps, in real document order.
MIXED_ORDER_INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemaps/categories-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://example.com/google-news-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemaps/old-2026-8-1-5.xml</loc><lastmod>2026-08-01</lastmod></sitemap>
  <sitemap><loc>https://example.com/sitemaps/recent-2026-9-11-15.xml</loc><lastmod>2026-09-13</lastmod></sitemap>
</sitemapindex>"""

CATEGORIES_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/category/coffee</loc></url>
</urlset>"""

RECENT_ARTICLES_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/news/coffee-prices-surge</loc><lastmod>2026-09-13</lastmod></url>
</urlset>"""


def test_discover_urls_follows_one_level_of_sitemapindex_nesting():
    def fetch(url):
        if url == "https://example.com/sitemap.xml":
            return _Resp(SITEMAP_INDEX)
        if "2026-09-13" in url:
            return _Resp(SUB_SITEMAP_1)
        if "2026-09-12" in url:
            return _Resp(SUB_SITEMAP_2)
        return _Resp("", status=404)

    r = sd.discover_urls("example.com", fetch_fn=fetch)
    assert r["ok"] is True
    assert r["_summary"]["raw_sitemap_urls"] == 3  # 2 + 1 across the two followed sub-sitemaps
    assert len(r["urls"]) == 3


def test_discover_urls_stops_at_max_nested_sub_sitemaps():
    calls = []

    def fetch(url):
        calls.append(url)
        if url == "https://example.com/sitemap.xml":
            return _Resp(SITEMAP_INDEX)
        return _Resp(SUB_SITEMAP_1)

    sd.discover_urls("example.com", fetch_fn=fetch, max_nested=1)
    # 1 call for the index + 1 for the single sub-sitemap it's allowed to follow.
    assert len(calls) == 2


def test_discover_urls_filters_by_keyword_in_url_path():
    def fetch(url):
        if url == "https://example.com/sitemap.xml":
            return _Resp(SITEMAP_INDEX)
        if "2026-09-13" in url:
            return _Resp(SUB_SITEMAP_1)
        if "2026-09-12" in url:
            return _Resp(SUB_SITEMAP_2)
        return _Resp("", status=404)

    r = sd.discover_urls("example.com", keywords=["coffee"], fetch_fn=fetch)
    assert r["_summary"]["matched_keywords"] == 2
    assert all("coffee" in u for u in r["urls"])
    assert "election-update" not in " ".join(r["urls"])


def test_discover_urls_handles_a_plain_urlset_with_no_index():
    def fetch(url):
        return _Resp(PLAIN_URLSET)

    r = sd.discover_urls("example.com", fetch_fn=fetch)
    assert r["ok"] is True
    assert r["_summary"]["raw_sitemap_urls"] == 2


def test_discover_urls_respects_cap():
    def fetch(url):
        return _Resp(PLAIN_URLSET)

    r = sd.discover_urls("example.com", cap=1, fetch_fn=fetch)
    assert len(r["urls"]) == 1


def test_discover_urls_honest_error_on_404():
    def fetch(url):
        return _Resp("not found", status=404)

    r = sd.discover_urls("example.com", fetch_fn=fetch)
    assert r["ok"] is False
    assert "404" in r["error"]
    assert r["urls"] == []


def test_discover_urls_honest_error_on_fetch_exception():
    def boom(url):
        raise ConnectionError("dns failure")

    r = sd.discover_urls("example.com", fetch_fn=boom)
    assert r["ok"] is False
    assert "dns failure" in r["error"]


def test_discover_urls_rejects_empty_domain():
    r = sd.discover_urls("", fetch_fn=lambda u: _Resp(PLAIN_URLSET))
    assert r["ok"] is False
    assert "empty domain" in r["error"]


def test_discover_urls_one_dead_sub_sitemap_does_not_fail_the_whole_domain():
    def fetch(url):
        if url == "https://example.com/sitemap.xml":
            return _Resp(SITEMAP_INDEX)
        if "2026-09-13" in url:
            raise ConnectionError("timeout")
        if "2026-09-12" in url:
            return _Resp(SUB_SITEMAP_2)
        return _Resp("", status=404)

    r = sd.discover_urls("example.com", fetch_fn=fetch)
    assert r["ok"] is True
    assert r["_summary"]["raw_sitemap_urls"] == 1  # only the surviving sub-sitemap's entry


def test_discover_urls_prioritizes_recent_sub_sitemaps_over_document_order():
    """Real bug found live (Increment 9, electric scooters/Vietnam): thanhnien.vn's
    real sitemap index lists category/utility sub-sitemaps (no lastmod) BEFORE the
    actual dated article sub-sitemaps. Blindly following the first max_nested in
    document order picked up category/utility pages instead of recent articles,
    so real keyword matching against article URLs found nothing despite the site
    genuinely having thousands of indexed pages. Sorting by lastmod (most recent
    first, no-lastmod entries last) before truncating fixes this."""
    def fetch(url):
        if url == "https://example.com/sitemap.xml":
            return _Resp(MIXED_ORDER_INDEX)
        if "categories-sitemap" in url:
            return _Resp(CATEGORIES_SITEMAP)
        if "google-news-sitemap" in url:
            return _Resp("", status=404)  # not every real site's google-news sitemap exists
        if "recent-2026-9-11-15" in url:
            return _Resp(RECENT_ARTICLES_SITEMAP)
        if "old-2026-8-1-5" in url:
            return _Resp("<urlset></urlset>")
        return _Resp("", status=404)

    r = sd.discover_urls("example.com", max_nested=2, fetch_fn=fetch)
    assert r["ok"] is True
    # With max_nested=2, sorting by recency should pick the dated "recent" sub-sitemap
    # and one of the two no-lastmod ones (not both no-lastmod ones over the real one).
    assert "https://example.com/news/coffee-prices-surge" in r["urls"]


def test_parse_locs_with_lastmod_does_not_shift_lastmod_onto_the_wrong_loc():
    """Real bug found live while writing the recency-sort regression test above: the
    old parser extracted ALL <loc> values and ALL <lastmod> values as two flat lists
    and zipped them by position. The instant SOME entries in a document have no
    <lastmod> (exactly MIXED_ORDER_INDEX's real shape -- and thanhnien.vn's actual
    sitemap index), every date after the first gap silently shifts onto the wrong
    URL: e.g. the "categories" entry (no lastmod) was assigned the "old" entry's real
    lastmod, and "old"/"recent" (which DO have lastmod) came out as None. Parsing each
    <sitemap>/<url> block independently and matching <loc>/<lastmod> within that block
    fixes this regardless of which entries carry a lastmod at all."""
    entries = sd._parse_locs_with_lastmod(MIXED_ORDER_INDEX)
    by_loc = {e["loc"]: e["lastmod"] for e in entries}
    assert by_loc["https://example.com/sitemaps/categories-sitemap.xml"] is None
    assert by_loc["https://example.com/google-news-sitemap.xml"] is None
    assert by_loc["https://example.com/sitemaps/old-2026-8-1-5.xml"] == "2026-08-01"
    assert by_loc["https://example.com/sitemaps/recent-2026-9-11-15.xml"] == "2026-09-13"
