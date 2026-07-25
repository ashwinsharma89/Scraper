"""Archive round-trip lossless; auth password hashing; scheduler tick."""
import analysis
import archive
import auth
import market_intel
import scheduler
import storage


def _cfg():
    import config
    return config.run_wizard({
        "market": {"country": "Singapore", "languages": ["en"]},
        "product": {"brand": "Acme Cola", "category": "cola", "category_type": "fmcg_food"},
        "competitors": ["Fizzly"],
        "keywords": {"trend_terms": ["sugar-free"]},
    })


def _fake_call(prompt, model):
    import json
    n = prompt.count("] source=")
    return json.dumps([{
        "sentiment": "positive", "sentiment_score": 0.5, "language": "en",
        "summary_en": "good", "purchase_driver": "price", "trend_category": "sugar-free",
        "brand_focus": "target brand", "promo_mentioned": False, "emotion": "joy",
    } for _ in range(n)])


def test_archive_export_import_round_trips_losslessly(fresh_db, tmp_path):
    pid = storage.create_project("Acme Study", _cfg())
    r = storage.start_run(pid, "news", {"q": "x"})
    storage.save_items(pid, r, "news", [
        {"title": "Acme Cola review", "text": "tasty", "link": "http://a", "published": "2024-03-01"},
        {"title": "Second", "text": "cheap and nice", "link": "http://b", "published": "2024-03-02"},
    ])
    analysis.analyze_all(pid, call_fn=_fake_call, model="test-model")
    market_intel.add_cited_entry(pid, {
        "category": "Market size", "metric": "m", "value": "S$1", "source_name": "Src",
        "source_url": "http://s", "publication_date": "2024-01-01", "accessed_date": "2024-06-01",
        "confidence": "high"}, entered_by="alice")

    # Snapshot originals.
    orig_items = storage.list_items(pid)
    orig_hashes = sorted(i["content_hash"] for i in orig_items)
    orig_intel = storage.list_market_intel(pid)

    path = archive.export_project(pid, out_path=str(tmp_path / "study.mlz"))

    # Import into the SAME db as a new project (fresh id) — must not collide.
    new_pid = archive.import_project(path, new_name="Imported Study")
    assert new_pid != pid

    new_items = storage.list_items(new_pid)
    assert len(new_items) == len(orig_items)
    assert sorted(i["content_hash"] for i in new_items) == orig_hashes

    # Analysis survived and stays attached to the right items (by content hash).
    new_rows = storage.items_with_analysis(new_pid)
    new_by_hash = {r["content_hash"]: r for r in new_rows}
    for it in orig_items:
        nb = new_by_hash[it["content_hash"]]
        assert nb["sentiment"] == "positive"
        assert nb["trend_category"] == "sugar-free"
        assert nb["analysis_model"] == "test-model"

    new_intel = storage.list_market_intel(new_pid)
    assert len(new_intel) == len(orig_intel)
    assert new_intel[0]["source_url"] == "http://s"
    assert new_intel[0]["entered_by"] == "alice"


def test_password_hashing_roundtrip(fresh_db):
    auth.create_user("alice", "s3cret", is_admin=True)
    assert auth.authenticate("alice", "s3cret") is True
    assert auth.authenticate("alice", "wrong") is False
    assert auth.authenticate("nobody", "x") is False
    # Stored hash is NOT the plaintext password.
    user = storage.get_user("alice")
    assert user["password_hash"] != "s3cret"
    assert len(user["salt"]) == 32


def test_session_token_roundtrip():
    token = auth.make_session_token("bob")
    assert auth.read_session_token(token) == "bob"
    assert auth.read_session_token("tampered.token.value") is None


def test_scheduler_tick_fires_due(fresh_db, monkeypatch):
    pid = storage.create_project("P", _cfg())
    fired_jobs = []
    monkeypatch.setattr("jobs.enqueue",
                        lambda p, c, params, triggered_by=None: fired_jobs.append((p, c, triggered_by)))
    sid = scheduler.create_schedule(pid, "news", {}, interval_seconds=3600, first_run_in=0)
    fired = scheduler.tick()
    assert fired == 1
    assert fired_jobs[0][0] == pid and fired_jobs[0][1] == "news"
    # next_run advanced into the future -> not due again immediately.
    assert scheduler.tick() == 0
