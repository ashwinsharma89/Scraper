"""Wires category_discovery + site_intelligence + sitemap_discovery + generic_site
together into one real, end-to-end run for a single source type
(DESIGN_01_category-discovery.md §13, Increment 4's pilot). Reused unchanged by
Increment 9's generalization to further categories/source types — nothing here is
coffee- or India-specific.

Scope, deliberately narrow (matches the pilot's own stated scope, §13 row 4):
  - Takes an already-confirmed list of seed domains (§4 tier 1's output — a human or
    the ledger's auto-trust already decided these are worth trying; this module does
    not itself call the LLM or decide which sites to trust).
  - For each domain: reachability probe (reuses source_discovery._probe, not
    reinvented) -> sitemap discovery (§4 tier 2) -> generic fetch/parse per URL,
    capped per source.
  - If `relevance_terms` is given, each successfully extracted page is checked with
    the SAME primitive the News channel's relevance gate uses
    (scrapers.relevance.contains_any_term) against title+text, and the real
    kept/dropped counts are written back to the site_intelligence ledger via
    storage.record_site_outcome — this is what closes DESIGN_01 §4b's loop with a
    real, not fabricated, relevance verdict, not merely "extraction succeeded".
    Without `relevance_terms` the pipeline still runs and reports full fetch/extract
    diagnostics, but deliberately does NOT write to the ledger — writing kept/dropped
    without a real relevance verdict would silently redefine what those columns mean,
    which is exactly the kind of quiet metric-redefinition this codebase avoids.
  - Does NOT do worker-pool concurrency or job resumability (§8/§9) — those are a
    later, separate increment (§13 row 6), sequenced deliberately after this pilot
    proves the mechanism works at all on one source type.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# DESIGN_01 §12/§14 item 7: a starting point for discussion, not a derived fact.
DEFAULT_PER_SOURCE_CAP = 500


def run_source_type_pilot(
    category: str,
    seed_domains: List[str],
    keywords: Optional[List[str]] = None,
    *,
    relevance_terms: Optional[List[str]] = None,
    per_source_cap: int = DEFAULT_PER_SOURCE_CAP,
    probe_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
    sitemap_fetch_fn: Optional[Callable[[str], Any]] = None,
    page_fetch_fn: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """Run the real, end-to-end pipeline for one category across a confirmed seed-site
    list. Returns a report shaped like AUDIT_08's methodology — real counts at every
    stage, not just a final total, so a caller can see exactly where volume was lost.
    """
    from scrapers.generic_site import fetch_and_extract
    from scrapers.relevance import contains_any_term
    from sitemap_discovery import discover_urls
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
        site_report: Dict[str, Any] = {"domain": domain}
        home = domain if domain.startswith("http") else f"https://{domain}"

        p = probe(home)
        report["_summary"]["sites_probed"] += 1
        site_report["reachable"] = bool(p.get("reachable"))
        site_report["probe_note"] = p.get("note")
        if not site_report["reachable"]:
            site_report.update(urls_found=0, pages_ok=0, pages_failed=0)
            report["sites"].append(site_report)
            continue
        report["_summary"]["sites_reachable"] += 1

        sm = discover_urls(domain, keywords, cap=per_source_cap, fetch_fn=sitemap_fetch_fn)
        site_report["sitemap_ok"] = sm["ok"]
        site_report["sitemap_error"] = sm.get("error")
        site_report["raw_sitemap_urls"] = sm["_summary"]["raw_sitemap_urls"]
        site_report["urls_matched"] = sm["_summary"]["matched_keywords"]
        report["_summary"]["raw_sitemap_urls"] += sm["_summary"]["raw_sitemap_urls"]
        report["_summary"]["urls_matched_keywords"] += sm["_summary"]["matched_keywords"]

        extracted: List[Dict[str, Any]] = []
        fetch_errors: List[Dict[str, str]] = []
        for url in sm["urls"]:
            r = fetch_and_extract(url, fetch_fn=page_fetch_fn)
            report["_summary"]["pages_fetched"] += 1
            if r["ok"]:
                extracted.append(r)
                report["_summary"]["pages_extracted_ok"] += 1
            else:
                fetch_errors.append({"url": url, "error": r["error"]})
                report["_summary"]["pages_blocked_or_failed"] += 1
        site_report["pages_ok"] = len(extracted)
        site_report["pages_failed"] = len(fetch_errors)
        site_report["sample_errors"] = fetch_errors[:3]

        if relevance_terms:
            kept = [it for it in extracted
                   if contains_any_term(it["title"] + " " + it["text"], relevance_terms)]
            dropped_count = len(extracted) - len(kept)
            site_report["pages_relevant"] = len(kept)
            site_report["pages_dropped_irrelevant"] = dropped_count
            report["_summary"]["pages_relevant"] += len(kept)
            report["_summary"]["pages_dropped_irrelevant"] += dropped_count
            site_report["items"] = kept

            import storage
            was_blocked_only = len(extracted) == 0 and len(fetch_errors) > 0 and all(
                e["error"].startswith("blocked:") for e in fetch_errors
            )
            storage.record_site_outcome(domain, category, kept=len(kept),
                                       dropped=dropped_count, blocked=was_blocked_only)
        else:
            site_report["items"] = extracted

        report["sites"].append(site_report)

    return report
