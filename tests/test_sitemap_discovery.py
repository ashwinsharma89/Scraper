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
