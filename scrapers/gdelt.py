"""GDELT DOC 2.0 API collection.

sourcecountry comes from config; monthly chunking with 250 records/chunk. GDELT returns
METADATA ONLY (title/link/date/outlet/language) — there is no article body. This
limitation is documented in the export Methodology and never papered over.
"""
from __future__ import annotations

import json as _json
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from scrapers import relevance
from scrapers.base import ScrapeResult, relevance_terms
from scrapers.news import chunk_date_ranges

CHANNEL = "gdelt"
API = "https://api.gdeltproject.org/api/v2/doc/doc"


def build_query(terms: List[str], sourcecountry: str) -> str:
    """GDELT query string: OR-group of quoted terms, scoped to a sourcecountry."""
    quoted = [f'"{t}"' if " " in t else t for t in terms if t]
    q = f"({' OR '.join(quoted)})" if quoted else ""
    if sourcecountry:
        q = f"{q} sourcecountry:{sourcecountry}".strip()
    return q


def build_url(query: str, after: str, before: str, maxrecords: int = 250) -> str:
    from urllib.parse import quote

    start = after.replace("-", "") + "000000"
    end = before.replace("-", "") + "000000"
    return (
        f"{API}?query={quote(query)}&mode=ArtList&format=json"
        f"&maxrecords={maxrecords}&startdatetime={start}&enddatetime={end}"
    )


def parse_articles(payload: str) -> List[Dict[str, Any]]:
    """Parse GDELT JSON ArtList into normalized metadata items."""
    try:
        data = _json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return []
    out: List[Dict[str, Any]] = []
    for a in (data or {}).get("articles", []) or []:
        seendate = a.get("seendate", "") or ""
        # GDELT seendate looks like 20240115T120000Z -> ISO date.
        pub = seendate[:8]
        pub_iso = f"{pub[:4]}-{pub[4:6]}-{pub[6:8]}" if len(pub) == 8 and pub.isdigit() else seendate
        out.append(
            {
                "title": a.get("title", "") or "",
                "text": "",  # metadata-only; honestly empty
                "link": a.get("url", "") or "",
                "published": pub_iso,
                "extra": {
                    "outlet": a.get("domain", ""),
                    "language": a.get("language", ""),
                    "sourcecountry": a.get("sourcecountry", ""),
                    "metadata_only": True,
                },
            }
        )
    return out


def _default_fetch(url: str):
    from http_client import get_session

    return get_session().get(url)


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
            *, fetch_fn: Optional[Callable[[str], Any]] = None) -> ScrapeResult:
    params = params or {}
    fetch = fetch_fn or _default_fetch
    result = ScrapeResult(CHANNEL)

    sourcecountry = cfg.get("source_plan", {}).get("gdelt", {}).get("sourcecountry", "")
    if not sourcecountry:
        result.error("GDELT sourcecountry not configured — set it in the project source plan.")
        return result

    terms = relevance_terms(cfg)
    query = build_query(terms, sourcecountry)
    maxrecords = cfg.get("collection_settings", {}).get("gdelt_chunk_size", 250)

    today = date.today()
    start_date = params.get("start_date") or (today - timedelta(days=180)).isoformat()
    end_date = params.get("end_date") or today.isoformat()

    dropped = 0
    for window in chunk_date_ranges(start_date, end_date, "monthly"):
        url = build_url(query, window["after"], window["before"], maxrecords)
        try:
            resp = fetch(url)
            if getattr(resp, "status_code", 200) >= 400:
                result.error(f"GDELT chunk {window['after']}..{window['before']} -> HTTP {resp.status_code}")
                continue
            for item in parse_articles(getattr(resp, "text", "") or ""):
                # GDELT's server-side matching is loose and often returns country news
                # unrelated to the query. It's metadata-only, so validate the TITLE against
                # relevance terms — precision over volume.
                if terms and not relevance.contains_any_term(item.get("title", ""), terms):
                    dropped += 1
                    continue
                result.add(item)
        except Exception as exc:
            result.error(f"GDELT chunk {window['after']}..{window['before']} failed: {exc}")
    if dropped:
        result.diagnostics["irrelevant_dropped"] = dropped
        result.error(f"GDELT: dropped {dropped} item(s) whose title matched no relevance term "
                     f"(GDELT server-side matching is unreliable).")
    return result
