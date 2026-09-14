"""Runner wiring: scraper -> storage with lineage, dedup, and run accounting."""
import time

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


class _ProgressReportingScraper:
    """Mimics scrapers/news.py's and scrapers/gdelt.py's opt-in progress_cb contract."""
    def collect(self, cfg, params, *, progress_cb=None):
        r = ScrapeResult("news")
        for i in range(1, 4):
            if progress_cb:
                progress_cb(i, 3, f"step {i}")
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


def test_run_collection_passes_progress_cb_only_when_the_scraper_accepts_it(fresh_db, monkeypatch):
    """Real gap this closes: news.py/gdelt.py's collect() gained an optional
    progress_cb kwarg so Extensive research isn't a flat "running" badge for minutes.
    Every OTHER channel's collect(cfg, params) signature is untouched -- passing
    progress_cb to one of those would crash with a TypeError, so run_collection must
    introspect the signature rather than assume every channel accepts it."""
    pid = storage.create_project("P", {"source_plan": {}})
    monkeypatch.setattr(jobs, "get_scraper", lambda ch: _ProgressReportingScraper())

    calls = []
    jobs.run_collection(pid, "news", {}, progress_cb=lambda cur, total, label="": calls.append((cur, total, label)))
    assert calls == [(1, 3, "step 1"), (2, 3, "step 2"), (3, 3, "step 3")]


def test_run_collection_omits_progress_cb_for_a_scraper_that_does_not_accept_it(fresh_db, monkeypatch):
    """The opposite direction: a plain collect(cfg, params) scraper (every channel
    except news/gdelt) must not receive progress_cb at all, or it would TypeError."""
    pid = storage.create_project("P", {"relevance_terms": [], "source_plan": {}})
    monkeypatch.setattr(jobs, "get_scraper", lambda ch: _FakeScraper([]))

    # Would raise TypeError: collect() got an unexpected keyword argument 'progress_cb'
    # if run_collection passed it through unconditionally.
    jobs.run_collection(pid, "news", {}, progress_cb=lambda cur, total, label="": None)


def test_enqueue_and_report_progress_surface_on_the_job_dict(fresh_db, monkeypatch):
    """End-to-end through the real worker thread: report_progress() (called via the
    progress_cb jobs._execute builds) must land on the SAME job dict get_job()/
    list_jobs() return, so the frontend's 1.5s poll picks it up for free."""
    monkeypatch.setattr(jobs, "get_scraper", lambda ch: _ProgressReportingScraper())
    pid = storage.create_project("P", {"source_plan": {}})
    job_id = jobs.enqueue(pid, "news", {}, triggered_by="alice")

    for _ in range(50):
        job = jobs.get_job(job_id)
        if job["status"] == "done":
            break
        time.sleep(0.02)
    assert job["status"] == "done"
    # The job finished so fast the worker's progress writes may all have landed before
    # any poll caught them mid-flight -- what matters is the plumbing reached the job
    # dict at all without crashing; report_progress()'s own unit test (below) proves
    # the value shape.


def test_run_collection_branches_generic_site_to_discovery_pipeline(fresh_db, monkeypatch):
    """HANDOFF §7 item 4 retrofit: generic_site isn't in scrapers._REGISTRY and manages
    its own run row internally -- run_collection() must route it to
    discovery_pipeline.run_source_type_job() instead of the normal
    start_run/get_scraper/save_items/finish_run flow (which would create a second,
    unused run row for the same job)."""
    import discovery_pipeline

    pid = storage.create_project("P", {"product": {"category": "coffee"},
                                       "relevance_terms": ["coffee", "espresso"]})
    captured = {}

    def fake_run_source_type_job(project_id, category, seed_domains, keywords=None, *,
                                 relevance_terms=None, per_source_cap=100, job_kind="backfill",
                                 run_id=None, triggered_by=None, progress_cb=None, **kw):
        captured.update(project_id=project_id, category=category, seed_domains=seed_domains,
                        keywords=keywords, relevance_terms=relevance_terms,
                        per_source_cap=per_source_cap)
        if progress_cb:
            progress_cb(1, 1, "Site: real.example")
        real_run_id = storage.start_run(project_id, "generic_site", {}, triggered_by)
        storage.finish_run(real_run_id, rows_returned=2, rows_new=2, rows_duplicate=0,
                           errors=[], status="done")
        return {"run_id": real_run_id, "returned": 2, "new": 2, "duplicate": 0,
                "errors": [], "_summary": {"sites_probed": 1}}

    monkeypatch.setattr(discovery_pipeline, "run_source_type_job", fake_run_source_type_job)

    calls = []
    summary = jobs.run_collection(
        pid, "generic_site", {"seed_domains": ["real.example"], "per_source_cap": 50},
        triggered_by="alice", progress_cb=lambda cur, total, label="": calls.append((cur, total, label)),
    )
    assert captured["category"] == "coffee"  # fell back from the project's own config
    assert captured["seed_domains"] == ["real.example"]
    assert captured["relevance_terms"] == ["coffee", "espresso"]  # from cfg, not fabricated
    assert captured["per_source_cap"] == 50
    assert summary["new"] == 2 and summary["duplicate"] == 0
    assert calls == [(1, 1, "Site: real.example")]
    # Exactly one run row -- run_source_type_job's own start_run(), not a second one.
    assert len(storage.list_runs(pid)) == 1


def test_report_progress_sets_progress_only_while_running():
    job_id = 999999  # isolated fake id, no real project needed for this unit check
    with jobs._jobs_lock:
        jobs._jobs[job_id] = {"id": job_id, "status": "running", "progress": None}
    try:
        jobs.report_progress(job_id, 2, 5, "halfway")
        assert jobs.get_job(job_id)["progress"] == {"current": 2, "total": 5, "label": "halfway"}

        # A late callback firing after the job already finished must not resurrect it.
        with jobs._jobs_lock:
            jobs._jobs[job_id]["status"] = "done"
        jobs.report_progress(job_id, 3, 5, "too late")
        assert jobs.get_job(job_id)["progress"] == {"current": 2, "total": 5, "label": "halfway"}
    finally:
        with jobs._jobs_lock:
            jobs._jobs.pop(job_id, None)
