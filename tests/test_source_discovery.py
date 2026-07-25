"""AI source discovery: parse + validate (LLM and network mocked)."""
import json

import config
import source_discovery


def _cfg():
    return config.run_wizard({
        "market": {"country": "Malaysia", "languages": ["en", "ms"]},
        "product": {"brand": "Maggi", "category": "instant noodles", "category_type": "fmcg_food"},
        "competitors": ["Indomie"],
        "keywords": {"trend_terms": ["food safety"]},
    })


LLM_JSON = json.dumps({
    "news_rss": [{"url": "https://www.nst.com.my/feed", "outlet": "NST", "why": "major daily"},
                 {"url": "https://dead.example/rss", "outlet": "Dead", "why": "x"}],
    "ecommerce": [{"url": "https://shopee.com.my/search?keyword=Maggi", "platform": "Shopee", "why": "top marketplace"}],
    "forums": [{"url": "https://forum.lowyat.net", "name": "Lowyat", "why": "big MY forum"}],
    "subreddits": ["malaysia", "MalaysianFood"],
    "quick_commerce": [{"platform": "GrabMart", "web_scrapable": False, "note": "app-only"}],
    "social_note": "Instagram/TikTok are manual Tier-3.",
})


def test_parse_suggestions_caps_and_keys():
    s = source_discovery.parse_suggestions("noise " + LLM_JSON + " trailing")
    assert [c["outlet"] for c in s["news_rss"]] == ["NST", "Dead"]
    assert s["subreddits"] == ["malaysia", "MalaysianFood"]
    assert s["quick_commerce"][0]["web_scrapable"] is False


def test_suggest_sources_validates(monkeypatch):
    # Mock feed health: NST healthy, the dead one not.
    def fake_feed_health(urls):
        return [{"url": u, "healthy": ("nst" in u), "status": 200 if "nst" in u else 404,
                 "reason": None if "nst" in u else "HTTP 404", "entries": 3 if "nst" in u else 0}
                for u in urls]
    monkeypatch.setattr(config, "feed_health_check", fake_feed_health)
    # Mock reachability probe + autodiscovery (no real network).
    monkeypatch.setattr(source_discovery, "_probe",
                        lambda url: {"reachable": True, "status": 200, "note": None})
    monkeypatch.setattr(source_discovery, "discover_feed", lambda home, fetch=None: None)

    s = source_discovery.suggest_sources(_cfg(), call_fn=lambda p, m: LLM_JSON)

    rss = {c["outlet"]: c for c in s["news_rss"]}
    assert rss["NST"]["valid"] is True
    assert rss["Dead"]["valid"] is False and "autodiscovery failed" in rss["Dead"]["note"]
    assert s["ecommerce"][0]["valid"] is True
    assert s["forums"][0]["valid"] is True
    assert s["_summary"]["news_rss"] == 2


def test_discover_feed_from_homepage():
    HTML = ('<html><head>'
            '<link rel="alternate" type="application/rss+xml" href="/feed/news.xml">'
            '</head><body></body></html>')

    class R:
        status_code = 200
        text = HTML

    feed = source_discovery.discover_feed("https://outlet.example", fetch=lambda u: R())
    assert feed == "https://outlet.example/feed/news.xml"

    # No feed link -> None.
    class R2:
        status_code = 200
        text = "<html><head></head><body>no feed</body></html>"
    assert source_discovery.discover_feed("https://x.example", fetch=lambda u: R2()) is None


def test_autodiscovery_recovers_dead_guess(monkeypatch):
    # LLM guessed a dead feed URL but gave the homepage; autodiscovery + health recovers it.
    llm = json.dumps({"news_rss": [{"home": "https://nst.example", "url": "https://nst.example/bad",
                                    "outlet": "NST", "why": "x"}],
                      "ecommerce": [], "forums": [], "subreddits": [], "quick_commerce": [],
                      "social_note": ""})
    monkeypatch.setattr(config, "feed_health_check",
                        lambda urls: [{"url": u, "healthy": u.endswith("/feed"), "status": 200,
                                       "reason": None if u.endswith("/feed") else "HTTP 404",
                                       "entries": 2} for u in urls])
    monkeypatch.setattr(source_discovery, "discover_feed",
                        lambda home, fetch=None: "https://nst.example/feed")
    s = source_discovery.suggest_sources(_cfg(), call_fn=lambda p, m: llm)
    c = s["news_rss"][0]
    assert c["valid"] is True
    assert c["url"] == "https://nst.example/feed"
    assert "auto-discovered" in c["note"]


def test_prompt_includes_market_and_brand():
    p = source_discovery.build_prompt(_cfg())
    assert "Malaysia" in p and "Maggi" in p and "instant noodles" in p
    assert "search URL" in p.lower() or "SEARCH URL" in p
