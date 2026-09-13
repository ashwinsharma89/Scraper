"""New results-dashboard aggregates (DESIGN_01_category-discovery.md §12):
items_by_channel (raw volume regardless of analysis status) and items_by_domain
(per-site volume for the generic_site pipeline)."""
import analytics
import storage


def test_items_by_channel_counts_regardless_of_analysis_status(fresh_db):
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        {"title": "A", "text": "body", "link": "http://x/1"},
        {"title": "B", "text": "body", "link": "http://x/2"},
    ])
    r2 = storage.start_run(pid, "generic_site", {})
    storage.save_items(pid, r2, "generic_site", [
        {"title": "C", "text": "body", "link": "http://curlytales.com/1"},
    ])
    rows = analytics.items_by_channel(pid)
    by_channel = {r["channel"]: r for r in rows}
    assert by_channel["news"]["n"] == 2
    assert by_channel["news"]["analyzed_n"] == 0  # nothing analyzed yet
    assert by_channel["generic_site"]["n"] == 1


def test_items_by_channel_tracks_analyzed_count_separately(fresh_db):
    import analysis as analysis_mod

    pid = storage.create_project("P", {"product": {"brand": "", "category": "coffee"},
                                       "market": {"languages": ["en"]}, "competitors": [],
                                       "keywords": {"trend_terms": []}, "source_plan": {}})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [{"title": "A", "text": "coffee body", "link": "http://x/1"}])

    def fake_call(prompt, model=None):
        return ('[{"sentiment": "positive", "sentiment_score": 0.5, "summary_en": "x", '
               '"purchase_driver": "none", "trend_category": "other/emergent", '
               '"brand_focus": "category-generic", "language": "en"}]')

    analysis_mod.analyze_all(pid, call_fn=fake_call)
    rows = analytics.items_by_channel(pid)
    assert rows[0]["analyzed_n"] == 1


def test_items_by_domain_extracts_and_counts_real_domains(fresh_db):
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "generic_site", {})
    storage.save_items(pid, r, "generic_site", [
        {"title": "A", "text": "body", "link": "https://www.curlytales.com/a"},
        {"title": "B", "text": "body", "link": "https://curlytales.com/b"},
        {"title": "C", "text": "body", "link": "https://thebetterindia.com/c"},
    ])
    result = analytics.items_by_domain(pid)
    assert result["n"] == 3
    by_domain = {d["domain"]: d["n"] for d in result["domains"]}
    assert by_domain["curlytales.com"] == 2  # www. stripped, both count together
    assert by_domain["thebetterindia.com"] == 1


def test_items_by_domain_only_counts_the_given_source(fresh_db):
    pid = storage.create_project("P", {})
    r1 = storage.start_run(pid, "news", {})
    storage.save_items(pid, r1, "news", [{"title": "A", "text": "b", "link": "http://news.com/1"}])
    r2 = storage.start_run(pid, "generic_site", {})
    storage.save_items(pid, r2, "generic_site", [{"title": "B", "text": "b", "link": "http://blog.com/1"}])
    result = analytics.items_by_domain(pid, source="generic_site")
    assert result["n"] == 1
    assert result["domains"] == [{"domain": "blog.com", "n": 1}]


def test_items_by_domain_empty_when_nothing_collected(fresh_db):
    pid = storage.create_project("P", {})
    result = analytics.items_by_domain(pid)
    assert result["n"] == 0
    assert result["domains"] == []
