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


def test_market_filter_catches_demonym_only_mentions():
    """The false-negative bug: an article that only uses the demonym ('French') and
    never the country name ('France') must still be kept once market_terms includes
    both — proving the wizard's demonym fix actually closes the gap end-to-end."""
    RSS = """<?xml version='1.0'?><rss version='2.0'><channel><title>GN</title>
    <item><title>Acme Bakery expands</title><link>http://gn/fr</link>
      <description>Acme Bakery expands</description><pubDate>2026-03-01</pubDate></item>
    </channel></rss>"""
    # Article never says "France" — only the demonym. Outlet has no .fr signal either.
    ART = ("<html><body><article><h1>Acme Bakery expands</h1>"
          "<p>The French chain opened ten new stores this quarter, its CEO said.</p>"
          "</article></body></html>")

    def fetch(url):
        if "news.google.com/rss/search" in url:
            return _Resp(RSS)
        return _Resp(ART, url="https://global-food-news.example/x")  # non-.fr outlet

    cfg = {
        "relevance_terms": ["Acme Bakery"],
        # market_terms as the WIZARD now produces them: name + demonym.
        "market": {"country": "France", "country_code": "FR", "cctld": ".fr",
                  "market_terms": ["France", "French"], "languages": ["en"]},
        "source_plan": {"google_news_feeds": [{"language": "en", "structure": "brand",
            "url": "https://news.google.com/rss/search?q=Acme&hl=en-FR&gl=FR&ceid=FR:en"}],
            "rss_feeds": []},
        "collection_settings": {"news_chunk": "none", "market_filter": True},
    }
    res = news.collect(cfg, {"start_date": "2026-03-01", "end_date": "2026-03-31"}, fetch_fn=fetch)
    assert len(res.items) == 1  # kept via the demonym, despite no country-name mention
    assert res.diagnostics.get("off_market_dropped", 0) == 0


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


def test_bing_news_feed_flows_through_same_pipeline():
    """Bing News items must get relevance validation, market filtering, first-paragraph
    text, and engine provenance — the same pipeline as Google News, not a separate path."""
    BING_RSS = """<?xml version='1.0'?><rss version='2.0'><channel><title>Bing</title>
    <item><title>Maggi backs Malaysian women entrepreneurs</title>
      <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.nst.com.my%2fx</link>
      <description>Maggi backs Malaysian women entrepreneurs</description>
      <pubDate>2026-03-01</pubDate></item>
    <item><title>Unrelated sports headline</title>
      <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fsome-sports-site.com%2fy</link>
      <description>Unrelated sports headline</description><pubDate>2026-03-02</pubDate></item>
    </channel></rss>"""
    ART_MY = ("<html><body><article><h1>Maggi backs Malaysian women</h1>"
             "<p>The KEMAS-backed programme ran across Malaysia this quarter, organisers said.</p>"
             "</article></body></html>")

    def fetch(url):
        if "bing.com/news/search" in url:
            return _Resp(BING_RSS)
        if "url=https%3a%2f%2fwww.nst.com.my" in url:
            # Simulate the normal HTTP redirect Bing performs (verified live: it's a
            # plain redirect, not an obfuscated token like Google News).
            return _Resp(ART_MY, url="https://www.nst.com.my/x")
        if "url=https%3a%2f%2fsome-sports-site.com" in url:
            return _Resp("<html><body><article><h1>Unrelated sports headline</h1>"
                        "<p>A local team won its match yesterday.</p></article></body></html>",
                        url="https://some-sports-site.com/y")
        return _Resp("", status=404)

    cfg = {
        "relevance_terms": ["Maggi"],
        "market": {"country": "Malaysia", "country_code": "MY", "cctld": ".my",
                  "market_terms": ["Malaysia", "Malaysian"], "languages": ["en"]},
        "source_plan": {"google_news_feeds": [], "rss_feeds": [],
            "bing_news_feeds": [{"language": "en", "structure": "brand",
                "url": "https://www.bing.com/news/search?q=Maggi&format=RSS"}]},
        "collection_settings": {"news_chunk": "none", "market_filter": True},
    }
    res = news.collect(cfg, {"start_date": "2026-03-01", "end_date": "2026-03-31"}, fetch_fn=fetch)
    titles = [i["title"] for i in res.items]
    assert "Maggi backs Malaysian women entrepreneurs" in titles  # relevant, kept
    assert "Unrelated sports headline" not in titles              # irrelevant, dropped

    kept = res.items[0]
    assert kept["extra"]["engine"] == "bing_news"       # accurate provenance
    assert kept["extra"]["is_google_news"] is True       # query-scoped semantics reused
    assert "KEMAS" in kept["text"]                       # real first-paragraph text
    assert kept["link"] == "https://www.nst.com.my/x"    # redirect resolved to the real article


def test_bing_news_can_be_disabled():
    def fetch(url):
        return _Resp("<rss/>")  # would error if actually called
    called = {"bing": False}

    def tracking_fetch(url):
        if "bing.com" in url:
            called["bing"] = True
        return _Resp("<rss version='2.0'><channel></channel></rss>")

    cfg = {"relevance_terms": ["Maggi"], "market": {"languages": ["en"]},
           "source_plan": {"google_news_feeds": [], "rss_feeds": [],
               "bing_news_feeds": [{"language": "en", "structure": "brand",
                   "url": "https://www.bing.com/news/search?q=Maggi&format=RSS"}]},
           "collection_settings": {"news_chunk": "none"}}
    news.collect(cfg, {"bing_news": False}, fetch_fn=tracking_fetch)
    assert called["bing"] is False


def test_google_news_paraphrased_mention_is_stored_not_dropped():
    """Structural gap #3 fix: a Google News item whose title/body never literally says
    the brand ("Maggi") but is clearly a paraphrased mention ("instant noodle price
    hikes") is now STORED with relevance_precheck=False instead of hard-dropped —
    Claude's brand_focus tag makes the final call during Analyze, not a keyword gate."""
    RSS = """<?xml version='1.0'?><rss version='2.0'><channel><title>GN</title>
    <item><title>Instant noodle prices climb across Malaysia</title><link>http://gn/x</link>
      <description>Instant noodle prices climb across Malaysia</description><pubDate>2026-03-01</pubDate></item>
    </channel></rss>"""
    # Body never says "Maggi" at all — paraphrase only.
    ART = ("<html><body><article><h1>Instant noodle prices climb across Malaysia</h1>"
          "<p>Shoppers say their favourite instant noodle brand has gotten pricier "
          "this quarter, retailers in Kuala Lumpur confirmed.</p></article></body></html>")

    def fetch(url):
        if "news.google.com/rss/search" in url:
            return _Resp(RSS)
        return _Resp(ART, url="https://www.thestar.com.my/x")  # .my outlet -> passes market gate

    cfg = {
        "relevance_terms": ["Maggi"],  # the literal keyword that will NOT be found
        "market": {"country": "Malaysia", "country_code": "MY", "cctld": ".my",
                  "market_terms": ["Malaysia", "Malaysian"], "languages": ["en"]},
        "source_plan": {"google_news_feeds": [{"language": "en", "structure": "category_generic",
            "url": "https://news.google.com/rss/search?q=instant+noodles&hl=en-MY&gl=MY&ceid=MY:en"}],
            "rss_feeds": []},
        "collection_settings": {"news_chunk": "none", "market_filter": True},
    }
    res = news.collect(cfg, {"start_date": "2026-03-01", "end_date": "2026-03-31"}, fetch_fn=fetch)
    assert len(res.items) == 1  # stored, not dropped
    item = res.items[0]
    assert item["extra"]["relevance_precheck"] is False  # marked for the semantic backstop
    assert item["extra"]["matched_in"] is None  # honestly: no keyword matched


def test_rss_paraphrased_mention_still_dropped_unscoped_feeds_have_no_bound():
    """A direct RSS feed is an UNSCOPED full firehose (not built from a keyword query),
    so relaxing the relevance gate there has no volume bound at all. The hard drop must
    stay for RSS — only Google News (keyword-scoped) gets the semantic backstop."""
    RSS = """<?xml version='1.0'?><rss version='2.0'><channel><title>Outlet feed</title>
    <item><title>Weather turns cooler this week</title><link>http://rss/weather</link>
      <description>Weather turns cooler this week</description><pubDate>2026-03-01</pubDate></item>
    </channel></rss>"""

    def fetch(url):
        return _Resp(RSS)

    cfg = {
        "relevance_terms": ["Maggi"],
        "market": {"languages": ["en"]},
        "source_plan": {"google_news_feeds": [], "rss_feeds": ["https://outlet.example/feed"]},
        "collection_settings": {"news_chunk": "none"},
    }
    res = news.collect(cfg, {"fetch_bodies": False}, fetch_fn=fetch)
    assert res.items == []  # correctly dropped — no keyword match, unscoped feed


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


def test_rss_summary_used_as_first_paragraph_when_body_unextractable():
    """Direct RSS feed: article page has no <p> body (JS-rendered), but the feed's own
    <description> is the real lead paragraph — it becomes the stored text (not the title)."""
    LEAD = "KUALA LUMPUR: Maggi noodles remain a staple as prices hold steady this quarter, retailers said."
    RSS = f"""<?xml version='1.0'?><rss version='2.0'><channel><title>BH</title>
    <item><title>Maggi stays a staple - Berita Harian</title><link>https://www.bharian.com.my/x</link>
      <description>{LEAD}</description><pubDate>2026-03-01</pubDate></item></channel></rss>"""
    JS_PAGE = "<html><body><div id='app'></div><script>render()</script></body></html>"  # no <p>

    cfg = {"relevance_terms": ["Maggi"], "market": {"languages": ["en"]},
           "source_plan": {"google_news_feeds": [], "rss_feeds": ["https://www.bharian.com.my/feed"]},
           "collection_settings": {"news_chunk": "none"}}

    def fetch(url):
        if url.endswith("/feed"):
            return _Resp(RSS)
        return _Resp(JS_PAGE, url="https://www.bharian.com.my/x")  # real page, no extractable body

    res = news.collect(cfg, {}, fetch_fn=fetch)
    assert len(res.items) == 1
    item = res.items[0]
    # Stored text is the real lead paragraph from the feed, NOT the title echo.
    assert item["text"] == LEAD
    assert item["text"] != item["title"]


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
