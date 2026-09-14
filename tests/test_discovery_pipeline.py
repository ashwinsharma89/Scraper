"""End-to-end wiring of §1-§4 for one source type (DESIGN_01 §13 Increment 4's pilot
mechanism). Network fully mocked via injected probe/fetch functions."""
import threading
import time

import discovery_pipeline as dp
import storage


class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


URLSET = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://good.example/coffee/relevant-1</loc></url>
  <url><loc>https://good.example/coffee/relevant-2</loc></url>
  <url><loc>https://good.example/other/off-topic</loc></url>
</urlset>"""

ARTICLE_ABOUT_COFFEE = """<html><body><article>
<h1>A great coffee story</h1>
<p>Coffee shops across Bangalore are seeing a huge boom this year with new roasters
opening every month, drawing crowds of enthusiasts eager to try single-origin beans.</p>
<p>Baristas say demand for specialty coffee has never been higher, citing rising
interest in pour-over and cold brew among younger customers across the city.</p>
</article></body></html>"""

ARTICLE_ABOUT_SOMETHING_ELSE = """<html><body><article>
<h1>City council approves new park</h1>
<p>The city council voted unanimously to approve funding for a new public park near
the riverside, with construction expected to begin next spring after a long review.</p>
<p>Residents welcomed the decision after years of lobbying for more green space in
the rapidly growing neighborhood, citing the need for family-friendly outdoor areas.</p>
</article></body></html>"""


def _reachable_probe(url):
    return {"reachable": True, "status": 200, "note": None}


def _unreachable_probe(url):
    return {"reachable": False, "status": None, "note": "ConnectionError (unreachable)"}


def _sitemap_fetch(url):
    return _Resp(URLSET)


def _page_fetch_for(mapping):
    def fetch(url):
        return _Resp(mapping.get(url, ""), status=200 if url in mapping else 404)
    return fetch


def test_pilot_reports_full_funnel_counts_without_relevance_terms():
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
        "https://good.example/other/off-topic": ARTICLE_ABOUT_SOMETHING_ELSE,
    })
    report = dp.run_source_type_pilot(
        "coffee", ["good.example"], keywords=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    s = report["_summary"]
    assert s["sites_probed"] == 1
    assert s["sites_reachable"] == 1
    assert s["raw_sitemap_urls"] == 3
    assert s["urls_matched_keywords"] == 2  # keyword filter drops the off-topic one
    assert s["pages_fetched"] == 2
    assert s["pages_extracted_ok"] == 2
    # No relevance_terms given -> no relevance verdict computed at all.
    assert "pages_relevant" not in report["sites"][0]


def test_pilot_skips_ledger_write_when_no_relevance_terms_given(fresh_db):
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
    })
    dp.run_source_type_pilot(
        "coffee", ["good.example"], keywords=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert storage.get_site_intelligence("good.example", "coffee") is None


def test_pilot_computes_real_relevance_verdict_and_writes_to_ledger(fresh_db):
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
    })
    report = dp.run_source_type_pilot(
        "coffee", ["good.example"], keywords=["coffee"], relevance_terms=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    site = report["sites"][0]
    assert site["pages_relevant"] == 1  # only the genuinely coffee-related article
    assert site["pages_dropped_irrelevant"] == 1
    row = storage.get_site_intelligence("good.example", "coffee")
    assert row is not None
    assert row["items_kept"] == 1
    assert row["items_dropped"] == 1
    assert row["confidence"] == 0.5


def test_pilot_records_unreachable_site_without_attempting_sitemap_or_fetch():
    calls = {"sitemap": 0, "page": 0}

    def sitemap_fetch(url):
        calls["sitemap"] += 1
        return _Resp(URLSET)

    def page_fetch(url):
        calls["page"] += 1
        return _Resp(ARTICLE_ABOUT_COFFEE)

    report = dp.run_source_type_pilot(
        "coffee", ["dead.example"], probe_fn=_unreachable_probe,
        sitemap_fetch_fn=sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert report["_summary"]["sites_reachable"] == 0
    assert calls["sitemap"] == 0
    assert calls["page"] == 0
    assert report["sites"][0]["reachable"] is False


def test_pilot_handles_multiple_domains_independently():
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
        "https://good.example/other/off-topic": ARTICLE_ABOUT_SOMETHING_ELSE,
    })
    report = dp.run_source_type_pilot(
        "coffee", ["good.example", "dead.example"], keywords=["coffee"],
        probe_fn=lambda url: _reachable_probe(url) if "good" in url else _unreachable_probe(url),
        sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert report["_summary"]["sites_probed"] == 2
    assert report["_summary"]["sites_reachable"] == 1
    domains = {s["domain"] for s in report["sites"]}
    assert domains == {"good.example", "dead.example"}


def test_pilot_marks_all_relevant_dropped_as_blocked_when_extraction_totally_failed(fresh_db):
    def page_fetch(url):
        return _Resp("<html><body>Access Denied</body></html>", status=200)

    report = dp.run_source_type_pilot(
        "coffee", ["good.example"], keywords=["coffee"], relevance_terms=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert report["_summary"]["pages_extracted_ok"] == 0
    row = storage.get_site_intelligence("good.example", "coffee")
    assert row["times_blocked"] == 1


# --------------------------------------------------------------------------- #
# source_health circuit breaker integration (DESIGN_01 §7.4, increment 5) —
# only exercised when project_id is given.
# --------------------------------------------------------------------------- #
def test_pilot_without_project_id_never_touches_source_health():
    """No project_id -> no per-project state to check or update -- confirms the
    pipeline still runs exactly as Increment 4 shipped it when this optional param
    is omitted, with no DB access at all (no fresh_db needed for this test)."""
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
    })
    report = dp.run_source_type_pilot(
        "coffee", ["good.example"], keywords=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert "circuit_breaker_note" not in report["sites"][0]
    assert report["sites"][0]["stopped_early_by_circuit_breaker"] is False


def test_pilot_skips_a_domain_already_paused_from_a_prior_run(fresh_db):
    pid = storage.create_project("P", {})
    for _ in range(3):
        storage.record_source_attempt(pid, "good.example", "good.example", success=False)
    assert storage.get_source_health(pid, "good.example")["paused"] == 1

    calls = {"sitemap": 0, "page": 0}

    def sitemap_fetch(url):
        calls["sitemap"] += 1
        return _Resp(URLSET)

    def page_fetch(url):
        calls["page"] += 1
        return _Resp(ARTICLE_ABOUT_COFFEE)

    report = dp.run_source_type_pilot(
        "coffee", ["good.example"], keywords=["coffee"], project_id=pid,
        probe_fn=_reachable_probe, sitemap_fetch_fn=sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert calls["sitemap"] == 0
    assert calls["page"] == 0
    assert report["sites"][0]["skipped"] is True
    assert "already paused" in report["sites"][0]["circuit_breaker_note"]


def test_pilot_stops_a_domain_early_mid_run_after_hitting_the_failure_threshold(fresh_db):
    pid = storage.create_project("P", {})

    # Sitemap matches 2 URLs (see URLSET); both fail -- with pause_after=2 the second
    # failure should trip the breaker (nothing left to attempt after it either way here,
    # but the mechanism is exercised and the row is left correctly paused for next run).
    def page_fetch(url):
        return _Resp("thin", status=200)  # too short -> counted as a failure

    report = dp.run_source_type_pilot(
        "coffee", ["good.example"], keywords=["coffee"], project_id=pid, pause_after=2,
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    site = report["sites"][0]
    assert site["stopped_early_by_circuit_breaker"] is True
    row = storage.get_source_health(pid, "good.example")
    assert row["paused"] == 1
    assert row["consecutive_failures"] == 2


def test_pilot_counts_a_broken_sitemap_itself_as_a_failure(fresh_db):
    """A domain whose sitemap 404s forever must still accumulate consecutive_failures
    and eventually pause -- otherwise it would be retried on every single future run
    forever, since the per-URL loop never even runs when there are no URLs to fetch."""
    pid = storage.create_project("P", {})

    def broken_sitemap(url):
        return _Resp("not found", status=404)

    for _ in range(3):
        dp.run_source_type_pilot(
            "coffee", ["broken.example"], keywords=["coffee"], project_id=pid,
            probe_fn=_reachable_probe, sitemap_fetch_fn=broken_sitemap,
            page_fetch_fn=lambda u: _Resp(ARTICLE_ABOUT_COFFEE),
        )
    row = storage.get_source_health(pid, "broken.example")
    assert row["consecutive_failures"] == 3
    assert row["paused"] == 1


def test_pilot_records_success_and_keeps_a_healthy_domain_unpaused(fresh_db):
    pid = storage.create_project("P", {})
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_COFFEE,
    })
    dp.run_source_type_pilot(
        "coffee", ["good.example"], keywords=["coffee"], project_id=pid,
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    row = storage.get_source_health(pid, "good.example")
    assert row["paused"] == 0
    assert row["consecutive_failures"] == 0


# --------------------------------------------------------------------------- #
# run_source_type_job: concurrency + resumability + real item persistence
# (DESIGN_01 §8/§9, increment 6)
# --------------------------------------------------------------------------- #
OTHER_URLSET = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://other.example/coffee/relevant-1</loc></url>
</urlset>"""


def _sitemap_fetch_multi(url):
    if url.startswith("https://good.example"):
        return _Resp(URLSET)
    if url.startswith("https://other.example"):
        return _Resp(OTHER_URLSET)
    return _Resp("", status=404)


def test_job_creates_a_real_run_and_returns_its_id(fresh_db):
    pid = storage.create_project("P", {})
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
    })
    report = dp.run_source_type_job(
        pid, "coffee", ["good.example"], keywords=["coffee"], relevance_terms=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    run = storage.get_run(report["run_id"])
    assert run is not None
    assert run["status"] == "done"
    assert run["job_kind"] == "backfill"


def test_job_persists_real_items_with_raw_html_category_source_type(fresh_db):
    pid = storage.create_project("P", {})
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
    })
    report = dp.run_source_type_job(
        pid, "coffee", ["good.example"], keywords=["coffee"], relevance_terms=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    items = storage.list_items(pid, source="generic_site")
    assert len(items) == 1  # only the genuinely relevant one was persisted
    assert items[0]["category"] == "coffee"
    assert items[0]["source_type"] == "generic_site"
    assert items[0]["raw_html"] == ARTICLE_ABOUT_COFFEE
    assert report["_summary"]["pages_relevant"] == 1


def test_job_return_shape_matches_other_channels_job_summary(fresh_db):
    """jobs.py's job dict reads .new/.duplicate the same way for every channel's
    summary -- run_source_type_job() previously computed these internally (for
    storage.finish_run()) but never returned them, so a generic_site job's Collect
    tab row would have shown "—" for New/Dup forever."""
    pid = storage.create_project("P", {})
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
    })
    report = dp.run_source_type_job(
        pid, "coffee", ["good.example"], keywords=["coffee"], relevance_terms=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert report["returned"] == 1
    assert report["new"] == 1
    assert report["duplicate"] == 0


def test_job_reports_progress_as_each_domain_completes(fresh_db):
    pid = storage.create_project("P", {})
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://other.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
    })
    calls = []
    dp.run_source_type_job(
        pid, "coffee", ["good.example", "other.example"], keywords=["coffee"],
        relevance_terms=["coffee"], probe_fn=_reachable_probe,
        sitemap_fetch_fn=_sitemap_fetch_multi, page_fetch_fn=page_fetch,
        progress_cb=lambda cur, total, label: calls.append((cur, total, label)),
    )
    assert sorted(c[0] for c in calls) == [1, 2]
    assert all(c[1] == 2 for c in calls)
    assert all("Site:" in c[2] for c in calls)


def test_job_without_relevance_terms_persists_nothing(fresh_db):
    """No real relevance verdict -> nothing durable is stored, matching the same
    honesty rule the pilot already applies to the ledger."""
    pid = storage.create_project("P", {})
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
    })
    dp.run_source_type_job(
        pid, "coffee", ["good.example"], keywords=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert storage.list_items(pid, source="generic_site") == []


def test_job_checkpoints_each_domain_as_it_completes(fresh_db):
    pid = storage.create_project("P", {})
    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
        "https://other.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
    })
    report = dp.run_source_type_job(
        pid, "coffee", ["good.example", "other.example"], keywords=["coffee"],
        relevance_terms=["coffee"], probe_fn=_reachable_probe,
        sitemap_fetch_fn=_sitemap_fetch_multi, page_fetch_fn=page_fetch,
    )
    cp = storage.get_run_checkpoint(report["run_id"])
    assert set(cp["domains_done"].keys()) == {"good.example", "other.example"}
    # Checkpoint stores slim summaries, not full article text.
    assert "items" not in cp["domains_done"]["good.example"]


def test_job_resumes_and_skips_already_completed_domains(fresh_db):
    """The core resumability guarantee: a second call sharing run_id must not
    re-fetch a domain the first call already finished."""
    pid = storage.create_project("P", {})
    calls = {"good.example": 0, "other.example": 0}

    def sitemap_fetch(url):
        for d in calls:
            if url.startswith(f"https://{d}"):
                calls[d] += 1
        return _sitemap_fetch_multi(url)

    page_fetch = _page_fetch_for({
        "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
        "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
        "https://other.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
    })

    # "Run 1" only processes good.example (simulating a job that only got this far
    # before a crash/restart -- run_source_type_job itself doesn't crash, we just
    # call it once per domain to model the checkpoint state a real crash would leave).
    first = dp.run_source_type_job(
        pid, "coffee", ["good.example"], keywords=["coffee"], relevance_terms=["coffee"],
        probe_fn=_reachable_probe, sitemap_fetch_fn=sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert calls["good.example"] == 1
    run_id = first["run_id"]

    # "Run 2" resumes the SAME run_id with the full domain list -- good.example must
    # be skipped (already checkpointed), only other.example actually fetched.
    second = dp.run_source_type_job(
        pid, "coffee", ["good.example", "other.example"], keywords=["coffee"],
        relevance_terms=["coffee"], run_id=run_id, probe_fn=_reachable_probe,
        sitemap_fetch_fn=sitemap_fetch, page_fetch_fn=page_fetch,
    )
    assert calls["good.example"] == 1  # NOT re-fetched
    assert calls["other.example"] == 1
    assert second["resumed_domains"] == 1
    assert second["run_id"] == run_id
    # Final totals reflect the WHOLE job (both domains), not just this call's subset.
    assert second["_summary"]["sites_reachable"] == 2
    assert len(storage.list_items(pid, source="generic_site")) == 2


def test_job_domains_run_concurrently_not_sequentially(fresh_db):
    """Real proof of §8's throughput claim: two domains whose page fetch each sleeps
    briefly must complete in roughly ONE sleep's worth of wall time, not two, when
    processed through the thread pool."""
    pid = storage.create_project("P", {})

    def slow_page_fetch(url):
        time.sleep(0.15)
        return _Resp(ARTICLE_ABOUT_COFFEE)

    t0 = time.monotonic()
    dp.run_source_type_job(
        pid, "coffee", ["good.example", "other.example"], keywords=["coffee"],
        relevance_terms=["coffee"], max_workers=2, probe_fn=_reachable_probe,
        sitemap_fetch_fn=_sitemap_fetch_multi, page_fetch_fn=slow_page_fetch,
    )
    elapsed = time.monotonic() - t0
    # Sequential would be >= 3 * 0.15s (3 total page fetches across both domains);
    # concurrent (2 workers) should finish well under that.
    assert elapsed < 0.15 * 3 * 0.8


def test_job_requires_a_project_id_to_be_meaningful():
    """project_id is a required positional arg (unlike run_source_type_pilot) --
    confirms the signature enforces this rather than silently accepting None."""
    import inspect
    sig = inspect.signature(dp.run_source_type_job)
    assert list(sig.parameters)[0] == "project_id"
    assert sig.parameters["project_id"].default is inspect.Parameter.empty


def test_job_marks_status_done_with_errors_when_a_worker_raises(fresh_db):
    pid = storage.create_project("P", {})

    def boom_probe(url):
        if "bad" in url:
            raise RuntimeError("simulated crash")
        return _reachable_probe(url)

    report = dp.run_source_type_job(
        pid, "coffee", ["good.example", "bad.example"], keywords=["coffee"],
        relevance_terms=["coffee"], probe_fn=boom_probe,
        sitemap_fetch_fn=_sitemap_fetch_multi,
        page_fetch_fn=_page_fetch_for({
            "https://good.example/coffee/relevant-1": ARTICLE_ABOUT_COFFEE,
            "https://good.example/coffee/relevant-2": ARTICLE_ABOUT_SOMETHING_ELSE,
        }),
    )
    assert len(report["errors"]) == 1
    assert "simulated crash" in report["errors"][0]
    run = storage.get_run(report["run_id"])
    assert run["status"] == "done_with_errors"


def test_domain_concurrency_cap_serializes_two_overlapping_jobs_on_the_same_domain(fresh_db):
    """The realistic scenario §7.2 exists for: a daily job and a manual backfill both
    targeting the same domain at the same time. Two SEPARATE run_source_type_job calls
    (different runs) racing on "good.example" must never fetch it concurrently."""
    pid = storage.create_project("P", {})
    concurrent = {"current": 0, "max_seen": 0}
    lock = threading.Lock()

    def slow_page_fetch(url):
        with lock:
            concurrent["current"] += 1
            concurrent["max_seen"] = max(concurrent["max_seen"], concurrent["current"])
        time.sleep(0.1)
        with lock:
            concurrent["current"] -= 1
        return _Resp(ARTICLE_ABOUT_COFFEE)

    def run_job():
        dp.run_source_type_job(
            pid, "coffee", ["good.example"], keywords=["coffee"], relevance_terms=["coffee"],
            probe_fn=_reachable_probe, sitemap_fetch_fn=_sitemap_fetch,
            page_fetch_fn=slow_page_fetch,
        )

    threads = [threading.Thread(target=run_job) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert concurrent["max_seen"] == 1
