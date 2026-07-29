"""Structural gap #3: semantic relevance backstop via existing brand_focus tagging.

Items whose collection-time keyword match fails (Google News only) are stored, not
dropped, with extra.relevance_precheck=False. Claude's brand_focus tag (asked for on
every item regardless) becomes the final relevance arbiter: analytics excludes
brand_focus="unrelated" from headline stats, and relevance_recovery_stats reports how
that recovery is playing out.
"""
import json

import analytics
import storage


def _cfg():
    return {"product": {"brand": "Maggi", "category": "instant noodles"}, "competitors": [],
            "market": {"languages": ["en"]}, "keywords": {"trend_terms": ["price"]},
            "source_plan": {}}


def _seed_item(pid, run_id, title, precheck_ok, source="news"):
    storage.save_items(pid, run_id, source, [{
        "title": title, "text": f"body about {title}", "link": f"http://x/{title}",
        "extra": {"relevance_precheck": precheck_ok},
    }])


def _analyze_all(pid, tag_map):
    """tag_map: {title -> brand_focus}. Analyzes only the items named in tag_map (any
    unanalyzed item NOT in tag_map is deliberately left pending) — bypasses the
    batching/prompt machinery since we only need analysis rows with specific
    brand_focus values, which is what analytics operates on."""
    for item in storage.get_unanalyzed_items(pid, limit=1000):
        if item["title"] not in tag_map:
            continue
        storage.save_analysis(pid, item["id"], "test-model", {
            "sentiment": "positive", "sentiment_score": 0.5, "language": "en",
            "summary_en": "s", "purchase_driver": "price", "trend_category": "price",
            "brand_focus": tag_map[item["title"]], "promo_mentioned": False, "emotion": "joy",
        })


def test_headline_aggregates_exclude_unrelated_by_default(fresh_db):
    pid = storage.create_project("P", _cfg())
    r = storage.start_run(pid, "news", {})
    _seed_item(pid, r, "relevant one", True)
    _seed_item(pid, r, "relevant two", True)
    _seed_item(pid, r, "noise item", False)
    _analyze_all(pid, {"relevant one": "target brand", "relevant two": "target brand",
                       "noise item": "unrelated"})

    dash = analytics.dashboard(pid)
    # 3 items collected, but only 2 count toward the headline sentiment n (unrelated excluded).
    assert dash["total_items"] == 3
    assert dash["total_analyzed"] == 2

    channels = analytics.sentiment_by_channel(pid)
    assert channels[0]["n"] == 2

    drivers = analytics.top_purchase_drivers(pid)
    assert drivers["n"] == 2

    trends = analytics.trend_volume_over_time(pid)
    assert trends["n"] == 2

    verb = analytics.top_verbatims_per_theme(pid)
    assert verb["n"] == 2


def test_brand_vs_competitor_still_shows_unrelated_bucket(fresh_db):
    """Unlike the headline stats, this breakdown's whole point is to show how much of
    the corpus was unrelated — it must NOT silently hide that bucket."""
    pid = storage.create_project("P", _cfg())
    r = storage.start_run(pid, "news", {})
    _seed_item(pid, r, "relevant one", True)
    _seed_item(pid, r, "noise item", False)
    _analyze_all(pid, {"relevant one": "target brand", "noise item": "unrelated"})

    bvc = {row["brand_focus"]: row for row in analytics.brand_vs_competitor_sentiment(pid)}
    assert "unrelated" in bvc
    assert bvc["unrelated"]["n"] == 1
    assert bvc["target brand"]["n"] == 1


def test_relevance_recovery_stats_tracks_all_three_outcomes(fresh_db):
    pid = storage.create_project("P", _cfg())
    r = storage.start_run(pid, "news", {})
    _seed_item(pid, r, "recovered item", False)     # precheck failed, Claude confirms relevant
    _seed_item(pid, r, "junk item", False)           # precheck failed, Claude confirms unrelated
    _seed_item(pid, r, "pending item", False)        # precheck failed, not yet analyzed
    _seed_item(pid, r, "normal item", True)          # precheck passed (not part of the backstop)
    _analyze_all(pid, {"recovered item": "target brand", "junk item": "unrelated",
                       "normal item": "target brand"})
    # "pending item" deliberately left unanalyzed.

    stats = analytics.relevance_recovery_stats(pid)
    assert stats["precheck_failed_total"] == 3       # excludes the normal (precheck=True) item
    assert stats["recovered_relevant"] == 1
    assert stats["confirmed_unrelated"] == 1
    assert stats["pending_analysis"] == 1


def test_relevance_recovery_stats_empty_project(fresh_db):
    pid = storage.create_project("P", _cfg())
    stats = analytics.relevance_recovery_stats(pid)
    assert stats == {"precheck_failed_total": 0, "recovered_relevant": 0,
                     "confirmed_unrelated": 0, "pending_analysis": 0}
