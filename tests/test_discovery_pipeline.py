"""End-to-end wiring of §1-§4 for one source type (DESIGN_01 §13 Increment 4's pilot
mechanism). Network fully mocked via injected probe/fetch functions."""
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
