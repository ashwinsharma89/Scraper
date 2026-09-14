"""Aggregation endpoints for reporting.

EVERY aggregate returned here carries its ``n`` (sample size). Downstream, the export's
Confidence tab auto-flags any headline stat resting on < 100 items or a single segment
as "emerging / low-confidence". Aggregates never hide their sample size.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import storage

LOW_CONFIDENCE_THRESHOLD = 100


def _month_of(item: Dict[str, Any]) -> str:
    pub = (item.get("published") or "").strip()
    if len(pub) >= 7 and pub[4] == "-":
        return pub[:7]
    created = (item.get("created_at") or "")[:7]
    return created or "unknown"


def _net(counts: Counter, n: int) -> float:
    if n == 0:
        return 0.0
    return round((counts.get("positive", 0) - counts.get("negative", 0)) / n, 3)


def _analyzed_rows(project_id: int, source: Optional[str] = None,
                   exclude_unrelated: bool = True) -> List[Dict[str, Any]]:
    """Analyzed rows for headline aggregates.

    exclude_unrelated=True (the default for every "headline" stat) drops items Claude's
    own analysis tagged brand_focus="unrelated" — this is the semantic backstop for
    collection-time relevance: items whose keyword match was weak/absent are now stored
    (see scrapers/news.py) rather than hard-dropped, and this is where an actually-
    irrelevant one gets excluded from sentiment/driver/trend numbers without ever being
    deleted from the DB (still visible in the Items browser and raw exports).
    brand_vs_competitor_sentiment() explicitly wants the unrelated bucket VISIBLE (that's
    its whole point), so it passes exclude_unrelated=False.
    """
    rows = [r for r in storage.items_with_analysis(project_id, source) if r.get("sentiment")]
    if exclude_unrelated:
        rows = [r for r in rows if (r.get("brand_focus") or "").strip().lower() != "unrelated"]
    return rows


def sentiment_by_channel(project_id: int) -> List[Dict[str, Any]]:
    rows = _analyzed_rows(project_id)
    by_channel: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_channel[r["source"]].append(r)

    out = []
    for channel, items in sorted(by_channel.items()):
        counts = Counter(i["sentiment"] for i in items)
        n = len(items)
        scores = [i["sentiment_score"] for i in items if i.get("sentiment_score") is not None]
        lang_counts = Counter(i.get("language") or "unknown" for i in items)
        out.append({
            "channel": channel,
            "n": n,
            "positive": counts.get("positive", 0),
            "negative": counts.get("negative", 0),
            "neutral": counts.get("neutral", 0),
            "mixed": counts.get("mixed", 0),
            "net_score": _net(counts, n),
            "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
            "language_breakdown": dict(lang_counts),
            "low_confidence": n < LOW_CONFIDENCE_THRESHOLD,
        })
    return out


def sentiment_by_month(project_id: int) -> List[Dict[str, Any]]:
    rows = _analyzed_rows(project_id)
    by_month: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_month[_month_of(r)].append(r)
    out = []
    for month in sorted(by_month):
        items = by_month[month]
        counts = Counter(i["sentiment"] for i in items)
        n = len(items)
        out.append({"month": month, "n": n, "net_score": _net(counts, n),
                    "positive": counts.get("positive", 0), "negative": counts.get("negative", 0),
                    "low_confidence": n < LOW_CONFIDENCE_THRESHOLD})
    return out


def top_purchase_drivers(project_id: int, limit: int = 15) -> Dict[str, Any]:
    rows = _analyzed_rows(project_id)
    drivers = Counter()
    for r in rows:
        d = (r.get("purchase_driver") or "").strip()
        if d and d.lower() not in {"none", "null", "n/a"}:
            drivers[d.lower()] += 1
    total = sum(drivers.values())
    top = [{"driver": k, "count": v} for k, v in drivers.most_common(limit)]
    return {"n": total, "drivers": top, "low_confidence": total < LOW_CONFIDENCE_THRESHOLD}


def trend_volume_over_time(project_id: int) -> Dict[str, Any]:
    rows = _analyzed_rows(project_id)
    # trend_category -> month -> count
    grid: Dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    for r in rows:
        cat = r.get("trend_category") or "other/emergent"
        grid[cat][_month_of(r)] += 1
        totals[cat] += 1
    series = []
    for cat in sorted(grid, key=lambda c: totals[c], reverse=True):
        n = totals[cat]
        series.append({"trend_category": cat, "n": n, "by_month": dict(sorted(grid[cat].items())),
                       "low_confidence": n < LOW_CONFIDENCE_THRESHOLD})
    return {"n": sum(totals.values()), "series": series}


def brand_vs_competitor_sentiment(project_id: int) -> List[Dict[str, Any]]:
    # Explicitly include "unrelated" here — this breakdown's whole purpose is to show
    # how much of the analyzed corpus Claude judged unrelated to the brand/competitors.
    rows = _analyzed_rows(project_id, exclude_unrelated=False)
    by_focus: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        focus = r.get("brand_focus") or "unspecified"
        by_focus[focus].append(r)
    out = []
    for focus in sorted(by_focus):
        items = by_focus[focus]
        counts = Counter(i["sentiment"] for i in items)
        n = len(items)
        scores = [i["sentiment_score"] for i in items if i.get("sentiment_score") is not None]
        out.append({"brand_focus": focus, "n": n, "net_score": _net(counts, n),
                    "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
                    "low_confidence": n < LOW_CONFIDENCE_THRESHOLD})
    return out


def top_verbatims_per_theme(project_id: int, per_theme: int = 5) -> Dict[str, Any]:
    rows = _analyzed_rows(project_id)
    by_theme: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_theme[r.get("trend_category") or "other/emergent"].append(r)
    themes = []
    for theme, items in sorted(by_theme.items(), key=lambda kv: len(kv[1]), reverse=True):
        # Rank by absolute sentiment strength so the most emphatic quotes surface.
        ranked = sorted(items, key=lambda i: abs(i.get("sentiment_score") or 0), reverse=True)
        verbatims = [{
            "summary_en": v.get("summary_en"),
            "text": (v.get("text") or "")[:300],
            "sentiment": v.get("sentiment"),
            "source": v.get("source"),
            "link": v.get("link"),
            "language": v.get("language"),
        } for v in ranked[:per_theme]]
        themes.append({"theme": theme, "n": len(items), "verbatims": verbatims,
                       "low_confidence": len(items) < LOW_CONFIDENCE_THRESHOLD})
    return {"n": len(rows), "themes": themes}


def relevance_recovery_stats(project_id: int) -> Dict[str, Any]:
    """Visibility into the semantic-relevance backstop (structural gap #3 fix).

    Items whose collection-time keyword match failed are now stored instead of
    hard-dropped (Google News channel only — see scrapers/news.py), tagged
    extra.relevance_precheck=False, and left for Claude's brand_focus tag to make the
    final call during normal analysis. This reports how that's playing out: how many
    were recovered as genuinely relevant vs correctly confirmed unrelated vs still
    awaiting analysis — proof the mechanism finds real signal, not just noise.
    """
    rows = storage.items_with_analysis(project_id)
    precheck_failed = [r for r in rows if r.get("extra", {}).get("relevance_precheck") is False]
    recovered = [r for r in precheck_failed if r.get("sentiment")
                and (r.get("brand_focus") or "").strip().lower() != "unrelated"]
    confirmed_unrelated = [r for r in precheck_failed if r.get("sentiment")
                           and (r.get("brand_focus") or "").strip().lower() == "unrelated"]
    pending = [r for r in precheck_failed if not r.get("sentiment")]
    return {
        "precheck_failed_total": len(precheck_failed),
        "recovered_relevant": len(recovered),
        "confirmed_unrelated": len(confirmed_unrelated),
        "pending_analysis": len(pending),
    }


def items_by_channel(project_id: int) -> List[Dict[str, Any]]:
    """Raw collected volume per channel, regardless of analysis status (DESIGN_01
    §12's results dashboard — complements sentiment_by_channel, which only covers
    already-analyzed rows). This is the first place a study's real channel mix
    becomes visible: how much came from the 10 existing channels vs. the new
    generic_site pipeline (§13 increments 3-6)."""
    totals = storage.count_items_by_source(project_id)
    analyzed = Counter(r["source"] for r in storage.items_with_analysis(project_id) if r.get("sentiment"))
    out = []
    for channel in sorted(totals):
        n = totals[channel]
        out.append({
            "channel": channel, "n": n, "analyzed_n": analyzed.get(channel, 0),
            "low_confidence": n < LOW_CONFIDENCE_THRESHOLD,
        })
    return out


def items_by_domain(project_id: int, source: str = "generic_site", limit: int = 20) -> Dict[str, Any]:
    """Per-domain volume for the generic-site pipeline specifically (DESIGN_01 §12) —
    the concrete, per-study answer to "which of the discovered sites actually
    contributed content," directly reflecting site_intelligence's per-site learning
    (a domain with high volume here is exactly the kind of real track record that
    feeds record_site_outcome, §4b) rather than a hypothetical channel-level number.
    """
    rows = storage.list_items(project_id, source=source, limit=5000)
    counts: Counter = Counter()
    for r in rows:
        domain = urlparse(r.get("link") or "").netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        counts[domain or "(unknown)"] += 1
    total = sum(counts.values())
    domains = [{"domain": d, "n": n} for d, n in counts.most_common(limit)]
    return {"source": source, "n": total, "domains": domains,
           "low_confidence": total < LOW_CONFIDENCE_THRESHOLD}


def news_engine_split(project_id: int) -> Dict[str, Any]:
    """HANDOFF §7: surface the Bing/Google split in the UI, not just implicitly via the
    raw item count. Google News and Bing News are two INDEPENDENT indices over the
    same query (scrapers/news.py's whole rationale for running both) — this reports
    how many stored "news"-channel items came from each engine (extra.engine, set at
    collection time in scrapers/news.py's _collect_feed), the concrete, per-study
    evidence that running Bing alongside Google actually contributes items Google's
    own crawl missed, not just theoretical redundancy. Counts raw collected items
    (not just analyzed ones) — this is a collection-provenance stat, matching
    items_by_channel()/items_by_domain()'s convention, not an analysis stat."""
    rows = storage.list_items(project_id, source="news", limit=20000)
    counts: Counter = Counter()
    for r in rows:
        engine = (r.get("extra", {}) or {}).get("engine") or "unknown"
        counts[engine] += 1
    total = sum(counts.values())
    return {
        "total": total,
        "google_news": counts.get("google_news", 0),
        "bing_news": counts.get("bing_news", 0),
        "rss": counts.get("rss", 0),
        # An item is only ever stored under engine="bing_news" if dedup didn't already
        # match it to an earlier-stored item (Google News runs first within one
        # collect() call, per scrapers/news.py's ordering) -- so this really is Bing's
        # incremental, non-overlapping contribution in the common case, not just its
        # raw share. Honest caveat: if Bing was collected in an EARLIER separate run
        # than Google, dedup order flips and this undercounts Bing's true find rate.
        "bing_only_share": round(counts.get("bing_news", 0) / total, 3) if total else 0.0,
    }


def dashboard(project_id: int) -> Dict[str, Any]:
    """Live sentiment×channel dashboard with net scores and language breakdown."""
    channels = sentiment_by_channel(project_id)
    total_n = sum(c["n"] for c in channels)
    overall = Counter()
    langs = Counter()
    for c in channels:
        for k in ("positive", "negative", "neutral", "mixed"):
            overall[k] += c[k]
        for lang, cnt in c["language_breakdown"].items():
            langs[lang] += cnt
    total_items = sum(storage.count_items_by_source(project_id).values())
    total_stories = storage.count_unique_stories(project_id)
    return {
        "project_id": project_id,
        "total_analyzed": total_n,
        "total_items": total_items,
        # Syndication-adjusted: distinct near-duplicate story clusters. When this is
        # notably lower than total_items, a chunk of "items" are the same wire story
        # reprinted across outlets — the real independent-signal n-size is total_stories.
        "total_stories": total_stories,
        "syndication_ratio": round(1 - (total_stories / total_items), 3) if total_items else 0.0,
        "unanalyzed": storage.count_unanalyzed(project_id),
        "overall_net_score": _net(overall, total_n),
        "overall_sentiment": dict(overall),
        "language_breakdown": dict(langs),
        "by_channel": channels,
        "low_confidence_overall": total_n < LOW_CONFIDENCE_THRESHOLD,
    }
