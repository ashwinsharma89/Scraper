"""HANDOFF §7: surface the Bing/Google split -- how many stored "news" items came from
each engine (extra.engine, set at collection time in scrapers/news.py's _collect_feed)."""
import storage


def _seed(pid, run_id, title, engine):
    storage.save_items(pid, run_id, "news", [{
        "title": title, "text": f"body about {title}", "link": f"http://x/{title}",
        "extra": {"engine": engine},
    }])


def test_news_engine_split_counts_each_engine(fresh_db):
    import analytics

    pid = storage.create_project("P", {"source_plan": {}})
    run_id = storage.start_run(pid, "news", {})
    _seed(pid, run_id, "a", "google_news")
    _seed(pid, run_id, "b", "google_news")
    _seed(pid, run_id, "c", "bing_news")
    _seed(pid, run_id, "d", "rss")

    r = analytics.news_engine_split(pid)
    assert r["total"] == 4
    assert r["google_news"] == 2
    assert r["bing_news"] == 1
    assert r["rss"] == 1
    assert r["bing_only_share"] == 0.25


def test_news_engine_split_ignores_non_news_channels(fresh_db):
    import analytics

    pid = storage.create_project("P", {"source_plan": {}})
    run_id = storage.start_run(pid, "reddit", {})
    storage.save_items(pid, run_id, "reddit", [
        {"title": "r1", "text": "x", "link": "http://r/1", "extra": {"engine": "google_news"}},
    ])
    r = analytics.news_engine_split(pid)
    assert r["total"] == 0
    assert r["google_news"] == 0


def test_news_engine_split_handles_zero_items(fresh_db):
    import analytics

    pid = storage.create_project("P", {"source_plan": {}})
    r = analytics.news_engine_split(pid)
    assert r == {"total": 0, "google_news": 0, "bing_news": 0, "rss": 0, "bing_only_share": 0.0}


def test_news_engine_split_endpoint(fresh_db):
    from fastapi.testclient import TestClient

    import app as app_mod

    client = TestClient(app_mod.app)
    import os
    os.environ["MODE"] = "solo"
    r = client.post("/api/projects/wizard", json={
        "market": {"country": "Singapore", "languages": ["en"]},
        "product": {"brand": "Acme Cola", "category": "cola", "category_type": "fmcg_food"},
    })
    pid = r.json()["id"]
    run_id = storage.start_run(pid, "news", {})
    _seed(pid, run_id, "a", "bing_news")

    r2 = client.get(f"/api/projects/{pid}/analytics/news_engine_split")
    assert r2.status_code == 200
    assert r2.json()["bing_news"] == 1
