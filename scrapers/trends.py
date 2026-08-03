"""Google Trends collection via pytrends (lazy import).

Interest-over-time + related queries for the project's configured keywords, geo from
config. Values are a RELATIVE index (0-100), not absolute search volume — this is
recorded on every item and in the export limitation notes.

pytrends' OWN retry support is broken against the currently-installed urllib3 (its
``retries=``/``backoff_factor=`` constructor args build a ``Retry(method_whitelist=...)``
— a urllib3 kwarg renamed to ``allowed_methods`` years ago and removed entirely in
recent urllib3 — so passing them raises ``TypeError`` immediately; verified live). This
is why pytrends defaults to no retry at all. Google's Trends backend does rate-limit
fairly aggressively under repeated use (verified live: a request that succeeded once
started 429ing on subsequent attempts within the same session), so this module
implements its own retry-with-backoff around pytrends calls instead of relying on the
library's broken one.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from scrapers.base import ScrapeResult

CHANNEL = "trends"
RETRY_WAIT = 20.0
RETRY_ATTEMPTS = 2


def _call_with_retry(fn, *, wait: Optional[float] = None, attempts: Optional[int] = None):
    """Call fn(); on a rate-limit error, sleep and retry. Resolves wait/attempts at CALL
    time (not as default-argument values) so tests can monkeypatch RETRY_WAIT/
    RETRY_ATTEMPTS on the module — see scrapers/reddit.py for why this matters."""
    from pytrends.exceptions import ResponseError, TooManyRequestsError

    if wait is None:
        wait = RETRY_WAIT
    if attempts is None:
        attempts = RETRY_ATTEMPTS
    last_exc = None
    for attempt in range(attempts + 1):
        try:
            return fn()
        except (TooManyRequestsError, ResponseError) as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(wait)
    raise last_exc


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
        # NOTE: do not pass retries=/backoff_factor= here — see module docstring.
        pt = TrendReq(hl="en-US", tz=0)
        _call_with_retry(lambda: pt.build_payload(keywords, timeframe=timeframe, geo=geo))

        iot = _call_with_retry(pt.interest_over_time)
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
        related = _call_with_retry(pt.related_queries)
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
