"""Wires category_discovery + site_intelligence + sitemap_discovery + generic_site
together into real, end-to-end collection for a single source type
(DESIGN_01_category-discovery.md §13). Nothing here is coffee- or India-specific.

Two public entry points, deliberately different scopes:

``run_source_type_pilot`` — Increment 4's original pilot mechanism. Sequential,
synchronous, no persisted `runs` row, no item persistence. Kept exactly as it shipped
(same signature, same behavior) for ad-hoc measurement/exploration where creating a
real run and writing real items would be premature — e.g. trying a brand-new category
before deciding it's worth a real collection.

``run_source_type_job`` — Increment 6's production mechanism (§8 concurrency + §9
resumability). Creates/resumes a real `runs` row, processes domains CONCURRENTLY via
a thread pool (parallelism across domains — the per-domain concurrency cap, §7.2,
still bounds any single domain to one in-flight fetch sequence at a time, which
matters once two overlapping runs, e.g. a daily job and a manual backfill, target the
same domain), checkpoints each domain's outcome to `runs.checkpoint_json` the moment
it completes, and persists kept/relevant items via storage.save_items() — including,
for the first time, the raw_html/category/source_type columns migrations.py's _m003
added back in increment 1 but nothing populated until now.

Both share one internal per-domain worker, `_process_domain`, so the actual fetch/
parse/relevance/ledger/circuit-breaker logic exists in exactly one place.

Concurrency model (§8), and what was deliberately NOT built: the design's own text
proposes a fully separate dedicated-writer-thread-plus-queue so worker threads never
call into storage.py directly. This module's workers DO call storage.py directly
(record_source_attempt, record_site_outcome, save_items) — but storage.write_conn()
already holds a process-wide lock for its entire lifetime, so every write across every
thread is ALREADY serialized correctly; a separate queue+writer-thread would provide
the same correctness guarantee through different plumbing, not a stronger one. Given
this workload is network-bound (a fetch dwarfs a local SQLite commit), the queue
architecture's real benefit would be reduced lock contention — a performance tweak
with no evidence yet that it's needed, not a correctness requirement. Named here as a
disclosed simplification, not an oversight; if real daily-pipeline write contention
ever shows otherwise, that's the evidence to build it on.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

# DESIGN_01 §12/§14 item 7: a starting point for discussion, not a derived fact.
DEFAULT_PER_SOURCE_CAP = 500
DEFAULT_MAX_WORKERS = 4


def _process_domain(
    domain: str,
    category: str,
    keywords: Optional[List[str]],
    relevance_terms: Optional[List[str]],
    per_source_cap: int,
    project_id: Optional[int],
    pause_after: int,
    probe: Callable[[str], Dict[str, Any]],
    sitemap_fetch_fn: Optional[Callable[[str], Any]],
    page_fetch_fn: Optional[Callable[[str], Any]],
) -> Dict[str, Any]:
    """One domain's full probe -> sitemap -> fetch/extract -> relevance sequence.
    Pure with respect to its caller's report/summary bookkeeping — returns a
    self-contained site_report; the caller decides how to fold it into a run.
    """
    from scrapers.generic_site import fetch_and_extract
    from scrapers.relevance import contains_any_term
    from sitemap_discovery import discover_urls
    import storage as storage_mod

    site_report: Dict[str, Any] = {"domain": domain}

    if project_id is not None:
        existing_health = storage_mod.get_source_health(project_id, domain)
        if existing_health and existing_health["paused"]:
            site_report.update(
                reachable=None, skipped=True,
                circuit_breaker_note=(
                    f"skipped: already paused after {existing_health['consecutive_failures']} "
                    f"consecutive failures in a prior run"),
                urls_found=0, pages_ok=0, pages_failed=0, items=[],
            )
            return site_report

    home = domain if domain.startswith("http") else f"https://{domain}"
    p = probe(home)
    site_report["reachable"] = bool(p.get("reachable"))
    site_report["probe_note"] = p.get("note")
    if not site_report["reachable"]:
        site_report.update(urls_found=0, pages_ok=0, pages_failed=0, items=[])
        return site_report

    sm = discover_urls(domain, keywords, cap=per_source_cap, fetch_fn=sitemap_fetch_fn)
    site_report["sitemap_ok"] = sm["ok"]
    site_report["sitemap_error"] = sm.get("error")
    site_report["raw_sitemap_urls"] = sm["_summary"]["raw_sitemap_urls"]
    site_report["urls_matched"] = sm["_summary"]["matched_keywords"]

    if project_id is not None:
        # A broken/missing sitemap is itself a real operational failure for this
        # source, not merely "zero URLs found" — without recording it here, a domain
        # whose sitemap is permanently 404 would never accumulate failures and would
        # be retried, unpaused, on every single future run forever.
        storage_mod.record_source_attempt(
            project_id, domain, domain, success=sm["ok"],
            status=(sm["error"][:200] if not sm["ok"] else "ok"), pause_after=pause_after,
        )

    extracted: List[Dict[str, Any]] = []
    fetch_errors: List[Dict[str, str]] = []
    stopped_early = False
    for i, url in enumerate(sm["urls"]):
        r = fetch_and_extract(url, fetch_fn=page_fetch_fn)
        if r["ok"]:
            extracted.append(r)
        else:
            fetch_errors.append({"url": url, "error": r["error"]})

        if project_id is not None:
            health = storage_mod.record_source_attempt(
                project_id, domain, domain, success=r["ok"],
                status=(r["error"][:200] if not r["ok"] else "ok"), pause_after=pause_after,
            )
            if health["paused"]:
                remaining = len(sm["urls"]) - (i + 1)
                site_report["circuit_breaker_note"] = (
                    f"stopped early after {health['consecutive_failures']} consecutive "
                    f"failures this run — {remaining} remaining sitemap URLs not attempted")
                stopped_early = True
                break

    site_report["pages_fetched"] = len(extracted) + len(fetch_errors)
    site_report["pages_ok"] = len(extracted)
    site_report["pages_failed"] = len(fetch_errors)
    site_report["sample_errors"] = fetch_errors[:3]
    site_report["stopped_early_by_circuit_breaker"] = stopped_early

    if relevance_terms:
        kept = [it for it in extracted
               if contains_any_term(it["title"] + " " + it["text"], relevance_terms)]
        dropped_count = len(extracted) - len(kept)
        site_report["pages_relevant"] = len(kept)
        site_report["pages_dropped_irrelevant"] = dropped_count
        site_report["items"] = kept

        was_blocked_only = len(extracted) == 0 and len(fetch_errors) > 0 and all(
            e["error"].startswith("blocked:") for e in fetch_errors
        )
        storage_mod.record_site_outcome(domain, category, kept=len(kept),
                                       dropped=dropped_count, blocked=was_blocked_only)
    else:
        site_report["items"] = extracted

    return site_report


def run_source_type_pilot(
    category: str,
    seed_domains: List[str],
    keywords: Optional[List[str]] = None,
    *,
    relevance_terms: Optional[List[str]] = None,
    per_source_cap: int = DEFAULT_PER_SOURCE_CAP,
    project_id: Optional[int] = None,
    pause_after: int = 3,
    probe_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
    sitemap_fetch_fn: Optional[Callable[[str], Any]] = None,
    page_fetch_fn: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """Increment 4's pilot mechanism — sequential, no run/checkpoint, no item
    persistence. Returns a report shaped like AUDIT_08's methodology: real counts at
    every stage, not just a final total, so a caller can see exactly where volume was
    lost. Unchanged from Increment 4 (now implemented via the shared _process_domain
    worker, but with byte-identical behavior/signature).
    """
    from source_discovery import _probe

    probe = probe_fn or _probe
    category = (category or "").strip()

    report: Dict[str, Any] = {
        "category": category,
        "sites": [],
        "_summary": {
            "sites_probed": 0, "sites_reachable": 0,
            "raw_sitemap_urls": 0, "urls_matched_keywords": 0,
            "pages_fetched": 0, "pages_extracted_ok": 0, "pages_blocked_or_failed": 0,
            "pages_relevant": 0, "pages_dropped_irrelevant": 0,
        },
    }

    for domain in seed_domains:
        domain = (domain or "").strip()
        if not domain:
            continue

        site_report = _process_domain(domain, category, keywords, relevance_terms,
                                      per_source_cap, project_id, pause_after,
                                      probe, sitemap_fetch_fn, page_fetch_fn)
        report["sites"].append(site_report)

        if site_report.get("skipped"):
            continue
        report["_summary"]["sites_probed"] += 1
        if not site_report["reachable"]:
            continue
        report["_summary"]["sites_reachable"] += 1
        report["_summary"]["raw_sitemap_urls"] += site_report.get("raw_sitemap_urls", 0)
        report["_summary"]["urls_matched_keywords"] += site_report.get("urls_matched", 0)
        report["_summary"]["pages_fetched"] += site_report.get("pages_fetched", 0)
        report["_summary"]["pages_extracted_ok"] += site_report.get("pages_ok", 0)
        report["_summary"]["pages_blocked_or_failed"] += site_report.get("pages_failed", 0)
        if relevance_terms:
            report["_summary"]["pages_relevant"] += site_report.get("pages_relevant", 0)
            report["_summary"]["pages_dropped_irrelevant"] += site_report.get(
                "pages_dropped_irrelevant", 0)

    return report


def run_source_type_job(
    project_id: int,
    category: str,
    seed_domains: List[str],
    keywords: Optional[List[str]] = None,
    *,
    relevance_terms: Optional[List[str]] = None,
    per_source_cap: int = DEFAULT_PER_SOURCE_CAP,
    pause_after: int = 3,
    max_workers: int = DEFAULT_MAX_WORKERS,
    job_kind: str = "backfill",
    run_id: Optional[int] = None,
    triggered_by: Optional[str] = None,
    probe_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
    sitemap_fetch_fn: Optional[Callable[[str], Any]] = None,
    page_fetch_fn: Optional[Callable[[str], Any]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    """Increment 6's production mechanism: real run tracking, concurrent domain
    processing, checkpointed resumability, and real item persistence.

    Pass ``run_id`` to RESUME a previously started job — domains already present in
    that run's checkpoint are skipped entirely (no probe, no sitemap fetch, no page
    fetch), matching DESIGN_01 §9's "skip already-completed units, don't re-fetch
    them." Omit it to start a brand-new run.

    ``project_id`` is required here (unlike run_source_type_pilot) because a real run
    row, real persisted items, and the source_health circuit breaker are all
    project-scoped by nature — this function IS the "wire it into a real project"
    mechanism, not an ad-hoc exploration tool.

    progress_cb(current, total, label) — called as each domain FINISHES (domains run
    concurrently, so "current" advances out of submission order — matches how
    as_completed() naturally yields). Same optional, purely-additive contract as
    scrapers/news.py's/gdelt.py's progress_cb (see jobs.py's run_collection()).
    """
    from source_discovery import _probe
    from http_client import get_domain_concurrency_limiter
    import storage as storage_mod

    probe = probe_fn or _probe
    category = (category or "").strip()
    domains = [d.strip() for d in seed_domains if (d or "").strip()]

    params = {"category": category, "seed_domains": domains, "keywords": keywords,
             "relevance_terms": relevance_terms}
    if run_id is None:
        run_id = storage_mod.start_run(project_id, "generic_site", params,
                                       triggered_by=triggered_by, job_kind=job_kind)
        checkpoint: Dict[str, Any] = {"domains_done": {}}
    else:
        checkpoint = storage_mod.get_run_checkpoint(run_id)
        checkpoint.setdefault("domains_done", {})

    already_done = checkpoint["domains_done"]
    pending = [d for d in domains if d not in already_done]
    concurrency = get_domain_concurrency_limiter()

    def _run_one(domain: str) -> Dict[str, Any]:
        with concurrency.slot(domain):
            return _process_domain(domain, category, keywords, relevance_terms,
                                   per_source_cap, project_id, pause_after,
                                   probe, sitemap_fetch_fn, page_fetch_fn)

    errors: List[str] = []
    done_count = 0
    if pending:
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            futures = {pool.submit(_run_one, d): d for d in pending}
            for future in as_completed(futures):
                domain = futures[future]
                done_count += 1
                if progress_cb:
                    progress_cb(done_count, len(pending), f"Site: {domain}")
                try:
                    site_report = future.result()
                except Exception as exc:
                    site_report = {"domain": domain, "error": f"{type(exc).__name__}: {exc}",
                                   "items": [], "pages_ok": 0, "pages_failed": 0}
                    errors.append(f"{domain}: {site_report['error']}")

                counts = {"returned": 0, "new": 0, "duplicate": 0}
                items = site_report.get("items") or []
                if relevance_terms and items:
                    shaped = [{
                        "title": it["title"], "text": it["text"], "link": it["url"],
                        "published": it.get("published"), "raw_html": it.get("raw_html"),
                        "category": category, "source_type": "generic_site",
                    } for it in items]
                    counts = storage_mod.save_items(project_id, run_id, "generic_site", shaped)

                # Checkpoint a slim summary, not full article content — the items
                # themselves are already durably persisted via save_items() above;
                # duplicating their full text into checkpoint_json would bloat the
                # runs table for no benefit.
                slim = {k: v for k, v in site_report.items() if k != "items"}
                slim["rows_returned"] = counts["returned"]
                slim["rows_new"] = counts["new"]
                slim["rows_duplicate"] = counts["duplicate"]
                already_done[domain] = slim
                # Written immediately after EACH domain, not batched (§9) — a crash
                # here only ever loses the one in-flight domain, never prior ones.
                storage_mod.update_run_checkpoint(run_id, checkpoint)

    # Final totals are summed across the WHOLE checkpoint, not just this invocation's
    # pending subset — a resumed run's reported totals must reflect the entire job.
    summary = {
        "sites_probed": 0, "sites_reachable": 0, "raw_sitemap_urls": 0,
        "urls_matched_keywords": 0, "pages_fetched": 0, "pages_extracted_ok": 0,
        "pages_blocked_or_failed": 0, "pages_relevant": 0, "pages_dropped_irrelevant": 0,
    }
    rows_returned = rows_new = rows_duplicate = 0
    for slim in already_done.values():
        if slim.get("skipped"):
            continue
        summary["sites_probed"] += 1
        if not slim.get("reachable"):
            continue
        summary["sites_reachable"] += 1
        summary["raw_sitemap_urls"] += slim.get("raw_sitemap_urls", 0)
        summary["urls_matched_keywords"] += slim.get("urls_matched", 0)
        summary["pages_fetched"] += slim.get("pages_fetched", 0)
        summary["pages_extracted_ok"] += slim.get("pages_ok", 0)
        summary["pages_blocked_or_failed"] += slim.get("pages_failed", 0)
        summary["pages_relevant"] += slim.get("pages_relevant", 0)
        summary["pages_dropped_irrelevant"] += slim.get("pages_dropped_irrelevant", 0)
        rows_returned += slim.get("rows_returned", 0)
        rows_new += slim.get("rows_new", 0)
        rows_duplicate += slim.get("rows_duplicate", 0)

    all_done = all(d in already_done for d in domains)
    status = "done" if (all_done and not errors) else ("done_with_errors" if all_done else "error")
    if all_done:
        storage_mod.finish_run(run_id, rows_returned=rows_returned, rows_new=rows_new,
                               rows_duplicate=rows_duplicate, errors=errors, status=status)

    return {
        "run_id": run_id, "job_kind": job_kind, "category": category,
        "resumed_domains": len(domains) - len(pending),
        "sites": list(already_done.values()), "_summary": summary,
        "errors": errors,
        # Exposed so jobs.py can report this job through the SAME summary shape every
        # other channel's job uses (Collect tab's job table reads .new/.duplicate) —
        # previously only reached storage.finish_run(), never the caller.
        "returned": rows_returned, "new": rows_new, "duplicate": rows_duplicate,
    }
