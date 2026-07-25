"""Runner wiring: scraper -> storage with lineage, dedup, and run accounting."""
import jobs
import storage
from scrapers.base import ScrapeResult


class _FakeScraper:
    def __init__(self, items, errors=None):
        self._items = items
        self._errors = errors or []

    def collect(self, cfg, params):
        r = ScrapeResult("news")
        r.items = [dict(i) for i in self._items]
        r.errors = list(self._errors)
        return r


def test_run_collection_records_lineage_and_dedup(fresh_db, monkeypatch):
    pid = storage.create_project("P", {"relevance_terms": [], "source_plan": {}})
    items = [{"title": "A", "text": "body a", "link": "http://a"},
             {"title": "B", "text": "body b", "link": "http://b"}]
    monkeypatch.setattr(jobs, "get_scraper", lambda ch: _FakeScraper(items))

    s1 = jobs.run_collection(pid, "news", {}, triggered_by="alice")
    assert (s1["new"], s1["duplicate"]) == (2, 0)
    run1 = storage.get_run(s1["run_id"])
    assert run1["rows_new"] == 2 and run1["triggered_by"] == "alice"

    # Every item carries the producing run.
    for it in storage.list_items(pid):
        assert it["run_id"] == s1["run_id"]

    # Re-run: identical content -> all duplicates, item count unchanged.
    s2 = jobs.run_collection(pid, "news", {}, triggered_by="bob")
    assert (s2["new"], s2["duplicate"]) == (0, 2)
    assert len(storage.list_items(pid)) == 2

    # Audit trail attributes each run to its acting user.
    actions = [a["acting_user"] for a in storage.list_audit(pid)]
    assert "alice" in actions and "bob" in actions


def test_run_collection_marks_error_status(fresh_db, monkeypatch):
    pid = storage.create_project("P", {"source_plan": {}})

    class Boom:
        def collect(self, cfg, params):
            raise RuntimeError("scraper exploded")

    monkeypatch.setattr(jobs, "get_scraper", lambda ch: Boom())
    try:
        jobs.run_collection(pid, "news", {})
    except RuntimeError:
        pass
    runs = storage.list_runs(pid)
    assert runs[0]["status"] == "error"
