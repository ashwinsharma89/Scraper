"""News: date-chunk continuity, OR filter, end-to-end relevance with mocked fetch."""
from datetime import date

from scrapers import news


# --------------------------------------------------------------------------- #
# Date chunk continuity
# --------------------------------------------------------------------------- #
def test_monthly_chunks_no_gaps_or_overlaps():
    ranges = news.chunk_date_ranges("2024-01-15", "2024-04-10", "monthly")
    # Coverage endpoints.
    assert ranges[0]["after"] == "2024-01-15"
    assert ranges[-1]["before"] == "2024-04-10"
    # Contiguous: each window starts exactly where the previous ended.
    for prev, nxt in zip(ranges, ranges[1:]):
        assert prev["before"] == nxt["after"]
    # Monthly boundaries fall on the first of the month.
    assert {"after": "2024-02-01", "before": "2024-03-01"} in ranges


def test_weekly_chunks_contiguous():
    ranges = news.chunk_date_ranges("2024-01-01", "2024-01-29", "weekly")
    assert ranges[0]["after"] == "2024-01-01"
    assert ranges[-1]["before"] == "2024-01-29"
    for prev, nxt in zip(ranges, ranges[1:]):
        assert prev["before"] == nxt["after"]
    # Full coverage, no gaps: union of ranges == whole span.
    assert (date.fromisoformat(ranges[0]["after"]),
            date.fromisoformat(ranges[-1]["before"])) == (date(2024, 1, 1), date(2024, 1, 29))


def test_chunk_year_boundary():
    ranges = news.chunk_date_ranges("2023-12-10", "2024-02-05", "monthly")
    assert ranges[0]["after"] == "2023-12-10"
    assert {"after": "2024-01-01", "before": "2024-02-01"} in ranges
    assert ranges[-1]["before"] == "2024-02-05"


# --------------------------------------------------------------------------- #
# OR filter
# --------------------------------------------------------------------------- #
def test_or_filter_matches_any():
    kws = news.parse_or_keywords("price, launch, recall")
    assert news.matches_or_filter("New product launch announced", kws) is True
    assert news.matches_or_filter("Company recall of batch", kws) is True
    assert news.matches_or_filter("Quarterly earnings summary", kws) is False
    # Empty filter keeps everything.
    assert news.matches_or_filter("anything", []) is True


def test_inject_date_range_preserves_locale_params():
    base = "https://news.google.com/rss/search?q=%22Acme+Cola%22&hl=en-SG&gl=SG&ceid=SG:en"
    out = news.inject_date_range(base, "2024-01-01", "2024-02-01")
    assert "hl=en-SG" in out and "gl=SG" in out and "ceid=SG:en" in out
    assert "after:2024-01-01" in out and "before:2024-02-01" in out


# --------------------------------------------------------------------------- #
# End-to-end collect with mocked fetch
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, text, status=200, url=None):
        self.text = text
        self.status_code = status
        self.url = url


RSS = """<?xml version='1.0'?><rss version='2.0'><channel><title>GN</title>
<item><title>Acme Cola launches sugar-free line</title>
      <link>http://news/1</link><description>Acme Cola launches sugar-free line</description>
      <pubDate>2024-01-10</pubDate></item>
<item><title>Local weather stays mild</title>
      <link>http://news/2</link><description>Local weather stays mild this week</description>
      <pubDate>2024-01-11</pubDate></item>
</channel></rss>"""

ARTICLE_RELEVANT = """<html><body><article>
  <h1>Acme Cola launches sugar-free line</h1>
  <p>Acme Cola said its new sugar-free variant will reach shelves next month.</p>
  <p>The company cited demand for lower-sugar drinks.</p>
</article></body></html>"""

ARTICLE_WEATHER = """<html><body><article>
  <h1>Local weather stays mild</h1>
  <p>Forecasters expect calm conditions with no rain.</p>
  <aside class="related"><a>Acme Cola news</a></aside>
</article></body></html>"""


def _cfg():
    return {
        "relevance_terms": ["Acme Cola", "Fizzly"],
        "market": {"languages": ["en"]},
        "source_plan": {
            "google_news_feeds": [
                {"language": "en", "structure": "brand", "url":
                 "https://news.google.com/rss/search?q=%22Acme+Cola%22&hl=en-SG&gl=SG&ceid=SG:en"}
            ],
            "rss_feeds": [],
        },
        "collection_settings": {"news_chunk": "none"},
    }


def test_decode_google_news_url_recovers_publisher():
    import base64
    target = "https://www.nst.com.my/news/nation/2026/03/maggi-story"
    raw = b'\x08\x13"' + target.encode("utf-8") + b"\x01\x02"
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    gn = f"https://news.google.com/rss/articles/{token}?oc=5"
    assert news.decode_google_news_url(gn) == target
    # Non-Google URL -> None.
    assert news.decode_google_news_url("https://example.com/x") is None


def test_market_signal_rules():
    # Country name matches its demonym via substring.
    assert news.market_signal("MAGGI backs Malaysian women", "site.com", ["Malaysia"], ".my") is True
    # ccTLD match.
    assert news.market_signal("no geo words here", "nst.com.my", ["Malaysia"], ".my") is True
    # Neither -> off-market.
    assert news.market_signal("Pahari Maggi in Indian hills", "indianexpress.com", ["Malaysia"], ".my") is False
    # No market config -> never filters.
    assert news.market_signal("anything", "any.com", [], "") is True


MY_RSS = """<?xml version='1.0'?><rss version='2.0'><channel><title>GN</title>
<item><title>MAGGI backs Malaysian women entrepreneurs</title><link>http://gn/my</link>
      <description>MAGGI backs Malaysian women entrepreneurs</description><pubDate>2026-03-01</pubDate></item>
<item><title>Pahari Maggi conquers Indian hills</title><link>http://gn/in</link>
      <description>Pahari Maggi conquers Indian hills</description><pubDate>2026-03-02</pubDate></item>
</channel></rss>"""

ART_MY = "<html><body><article><h1>MAGGI backs Malaysian women</h1><p>The programme runs across Malaysia this year with KEMAS support for local entrepreneurs.</p></article></body></html>"
ART_IN = "<html><body><article><h1>Pahari Maggi conquers Indian hills</h1><p>A vendor in the Indian hills sells Maggi noodles to trekkers in Himachal.</p></article></body></html>"


def _cfg_my():
    return {
        "relevance_terms": ["Maggi"],
        "market": {"country": "Malaysia", "country_code": "MY", "cctld": ".my",
                   "market_terms": ["Malaysia"], "languages": ["en"]},
        "source_plan": {"google_news_feeds": [{"language": "en", "structure": "brand",
            "url": "https://news.google.com/rss/search?q=Maggi&hl=en-MY&gl=MY&ceid=MY:en"}],
            "rss_feeds": []},
        "collection_settings": {"news_chunk": "none", "market_filter": True},
    }


def test_market_filter_drops_indian_keeps_malaysian():
    def fetch(url):
        if "news.google.com/rss/search" in url:
            return _Resp(MY_RSS)
        if url == "http://gn/my":
            return _Resp(ART_MY, url="https://www.nst.com.my/news/x")
        if url == "http://gn/in":
            return _Resp(ART_IN, url="https://indianexpress.com/x")
        return _Resp("", status=404)

    res = news.collect(_cfg_my(), {"start_date": "2026-03-01", "end_date": "2026-03-31"}, fetch_fn=fetch)
    titles = [i["title"] for i in res.items]
    assert "MAGGI backs Malaysian women entrepreneurs" in titles
    assert "Pahari Maggi conquers Indian hills" not in titles          # off-market -> dropped
    assert res.diagnostics["off_market_dropped"] == 1
    # Stored text is the real first paragraph (not the title-echo summary).
    kept = [i for i in res.items if i["title"].startswith("MAGGI")][0]
    assert "KEMAS" in kept["text"]
    assert kept["extra"]["body_resolved"] is True


def test_market_filter_can_be_disabled():
    def fetch(url):
        if "news.google.com/rss/search" in url:
            return _Resp(MY_RSS)
        if url == "http://gn/my":
            return _Resp(ART_MY, url="https://www.nst.com.my/news/x")
        if url == "http://gn/in":
            return _Resp(ART_IN, url="https://indianexpress.com/x")
        return _Resp("", status=404)

    res = news.collect(_cfg_my(), {"start_date": "2026-03-01", "end_date": "2026-03-31",
                                   "market_only": False}, fetch_fn=fetch)
    titles = [i["title"] for i in res.items]
    assert "Pahari Maggi conquers Indian hills" in titles  # kept when filter off


def test_market_filter_uses_outlet_domain_when_article_unresolved():
    """Real-world Google News case: article URL is an obfuscated redirect that won't
    resolve, but the feed exposes the outlet's homepage — a .my outlet is kept, a
    foreign outlet with a geo-neutral title is dropped."""
    RSS = """<?xml version='1.0'?><rss version='2.0'><channel><title>GN</title>
    <item><title>Maggi backs women entrepreneurs</title>
      <link>https://news.google.com/rss/articles/CBMiMYtok1?oc=5</link>
      <description>Maggi backs women entrepreneurs</description>
      <source url="https://www.nst.com.my">NST Online</source><pubDate>2026-03-01</pubDate></item>
    <item><title>Maggi noodles trend among trekkers</title>
      <link>https://news.google.com/rss/articles/CBMiINtok2?oc=5</link>
      <description>Maggi noodles trend among trekkers</description>
      <source url="https://indianexpress.com">Indian Express</source><pubDate>2026-03-02</pubDate></item>
    </channel></rss>"""

    def fetch(url):
        if "news.google.com/rss/search" in url:
            return _Resp(RSS)
        if "news.google.com/rss/articles" in url:
            # Unresolved: interstitial page that stays on news.google.com.
            return _Resp("<html><body>interstitial</body></html>", url=url)
        return _Resp("", status=404)

    res = news.collect(_cfg_my(), {"start_date": "2026-03-01", "end_date": "2026-03-31"}, fetch_fn=fetch)
    titles = [i["title"] for i in res.items]
    assert "Maggi backs women entrepreneurs" in titles       # kept via .my outlet domain
    assert "Maggi noodles trend among trekkers" not in titles  # foreign outlet -> dropped
    assert res.diagnostics["off_market_dropped"] == 1
    kept = res.items[0]
    assert kept["extra"]["outlet"] == "NST Online"
    assert kept["extra"]["body_resolved"] is False  # honest: GN body wasn't resolved


def test_collect_keeps_relevant_drops_irrelevant():
    def fetch(url):
        if "news.google.com" in url:
            return _Resp(RSS)
        if url == "http://news/1":
            return _Resp(ARTICLE_RELEVANT, url="http://real/acme-1")
        if url == "http://news/2":
            return _Resp(ARTICLE_WEATHER, url="http://real/weather-2")
        return _Resp("", status=404)

    res = news.collect(_cfg(), {"start_date": "2024-01-01", "end_date": "2024-01-31"}, fetch_fn=fetch)
    titles = [i["title"] for i in res.items]
    # Relevant kept, weather (term only in related aside) dropped.
    assert "Acme Cola launches sugar-free line" in titles
    assert "Local weather stays mild" not in titles
    # Google News redirect resolved to the real outlet URL.
    kept = [i for i in res.items if i["title"].startswith("Acme Cola")][0]
    assert kept["link"] == "http://real/acme-1"
    assert "sugar-free" in kept["text"].lower()
