"""Google Trends collection via pytrends (lazy import).

Interest-over-time + related queries for the project's configured keywords, geo from
config. Values are a RELATIVE index (0-100), not absolute search volume — this is
recorded on every item and in the export limitation notes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from scrapers.base import ScrapeResult

CHANNEL = "trends"


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> ScrapeResult:
    params = params or {}
    result = ScrapeResult(CHANNEL)

    trends_cfg = cfg.get("source_plan", {}).get("trends", {})
    geo = trends_cfg.get("geo", "")
    keywords: List[str] = params.get("keywords") or trends_cfg.get("keywords") or []
    keywords = [k for k in keywords if k][:5]  # pytrends caps at 5 terms per request
    if not keywords:
        result.error("No keywords configured for Google Trends.")
        return result

    try:
        from pytrends.request import TrendReq
    except Exception:
        result.error("pytrends is not installed — Google Trends skipped (no data fabricated).")
        return result

    timeframe = params.get("timeframe", "today 12-m")
    try:
        pt = TrendReq(hl="en-US", tz=0)
        pt.build_payload(keywords, timeframe=timeframe, geo=geo)

        iot = pt.interest_over_time()
        if iot is not None and not iot.empty:
            for idx, row in iot.iterrows():
                for kw in keywords:
                    if kw in row:
                        result.add(
                            {
                                "title": f"Trend index: {kw}",
                                "text": f"{kw} interest index = {row[kw]} ({geo or 'worldwide'})",
                                "link": f"https://trends.google.com/trends/explore?geo={geo}&q={kw}",
                                "published": str(idx)[:10],
                                "extra": {"type": "interest_over_time", "keyword": kw,
                                          "index": int(row[kw]), "geo": geo, "relative_index": True},
                            }
                        )
        related = pt.related_queries()
        for kw, blocks in (related or {}).items():
            for kind in ("top", "rising"):
                df = (blocks or {}).get(kind)
                if df is not None and not df.empty:
                    for _, r in df.iterrows():
                        result.add(
                            {
                                "title": f"Related query ({kind}) for {kw}: {r['query']}",
                                "text": str(r["query"]),
                                "link": f"https://trends.google.com/trends/explore?geo={geo}&q={kw}",
                                "published": "",
                                "extra": {"type": f"related_{kind}", "seed": kw,
                                          "value": r.get("value"), "geo": geo},
                            }
                        )
    except Exception as exc:
        result.error(f"Google Trends failed: {exc}")
    return result
