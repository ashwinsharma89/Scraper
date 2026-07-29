"""Aggregation endpoints for reporting.

EVERY aggregate returned here carries its ``n`` (sample size). Downstream, the export's
Confidence tab auto-flags any headline stat resting on < 100 items or a single segment
as "emerging / low-confidence". Aggregates never hide their sample size.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

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


def _analyzed_rows(project_id: int, source: Optional[str] = None) -> List[Dict[str, Any]]:
    return [r for r in storage.items_with_analysis(project_id, source) if r.get("sentiment")]


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
    rows = _analyzed_rows(project_id)
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
