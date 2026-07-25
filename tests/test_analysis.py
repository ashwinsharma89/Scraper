"""Analysis: idempotency, retryable failed batches, aggregation n-sizes (Claude mocked)."""
import json

import analysis
import analytics
import storage


def _seed(pid, n, source="news"):
    r = storage.start_run(pid, source, {})
    items = [{"title": f"t{i}", "text": f"body {i} tasty", "link": f"http://x/{i}"} for i in range(n)]
    storage.save_items(pid, r, source, items)


def _fake_call(sentiments):
    """Return a call_fn that emits a JSON array with given sentiments (cycled)."""
    def call(prompt, model):
        # Count items by counting "[<idx>] source=" lines.
        n = prompt.count("] source=")
        arr = []
        for i in range(n):
            s = sentiments[i % len(sentiments)]
            arr.append({
                "sentiment": s, "sentiment_score": {"positive": 0.7, "negative": -0.7,
                                                     "neutral": 0.0, "mixed": 0.1}[s],
                "language": "en", "summary_en": f"summary {i}", "rating_signal": None,
                "purchase_driver": "taste", "usage_occasion": None,
                "trend_category": "sugar-free", "brand_focus": "target brand",
                "promo_mentioned": False, "emotion": "joy",
            })
        return "Here you go:\n" + json.dumps(arr)
    return call


def _cfg():
    return {"product": {"brand": "Acme Cola", "category": "cola"}, "competitors": ["Fizzly"],
            "market": {"languages": ["en"]}, "keywords": {"trend_terms": ["sugar-free"]},
            "source_plan": {}}


def test_analysis_is_idempotent(fresh_db):
    pid = storage.create_project("P", _cfg())
    _seed(pid, 5)
    call = _fake_call(["positive"])

    r1 = analysis.analyze_all(pid, call_fn=call, model="test-model")
    assert r1["analyzed"] == 5
    assert storage.count_unanalyzed(pid) == 0

    # Re-running analyzes nothing new (idempotent).
    r2 = analysis.analyze_all(pid, call_fn=call, model="test-model")
    assert r2["analyzed"] == 0
    # Exactly one analysis row per item.
    rows = storage.items_with_analysis(pid)
    assert len(rows) == 5
    assert all(row["analysis_model"] == "test-model" for row in rows)


def test_failed_batch_is_retryable(fresh_db):
    pid = storage.create_project("P", _cfg())
    _seed(pid, 3)

    calls = {"n": 0}

    def flaky(prompt, model):
        calls["n"] += 1
        if calls["n"] == 1:
            return "the model returned garbage, not json"
        return _fake_call(["neutral"])(prompt, model)

    # First batch errors -> nothing written, all still unanalyzed.
    r1 = analysis.analyze_batch(pid, call_fn=flaky)
    assert r1["status"] == "error"
    assert storage.count_unanalyzed(pid) == 3

    # Retry succeeds.
    r2 = analysis.analyze_batch(pid, call_fn=flaky)
    assert r2["status"] == "ok" and r2["analyzed"] == 3
    assert storage.count_unanalyzed(pid) == 0


def test_batch_size_is_12(fresh_db):
    pid = storage.create_project("P", _cfg())
    _seed(pid, 30)
    seen = {}

    def counting(prompt, model):
        n = prompt.count("] source=")
        seen["last"] = n
        return _fake_call(["positive"])(prompt, model)

    res = analysis.analyze_batch(pid, call_fn=counting)
    assert res["analyzed"] == 12  # one batch = 12 items
    assert seen["last"] == 12
    assert storage.count_unanalyzed(pid) == 18


def test_aggregates_carry_n_and_flag_low_confidence(fresh_db):
    pid = storage.create_project("P", _cfg())
    _seed(pid, 6, source="news")
    _seed(pid, 4, source="reddit")
    analysis.analyze_all(pid, call_fn=_fake_call(["positive", "negative", "neutral"]))

    dash = analytics.dashboard(pid)
    assert dash["total_analyzed"] == 10
    # < 100 items -> flagged low confidence.
    assert dash["low_confidence_overall"] is True
    for ch in dash["by_channel"]:
        assert "n" in ch and ch["low_confidence"] is True

    drivers = analytics.top_purchase_drivers(pid)
    assert drivers["n"] == 10  # every item had a driver ("taste")
    bvc = analytics.brand_vs_competitor_sentiment(pid)
    assert all("n" in row for row in bvc)
    trends = analytics.trend_volume_over_time(pid)
    assert trends["series"][0]["trend_category"] == "sugar-free"
