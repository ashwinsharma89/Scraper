"""Google Business reviews via the Places API (key from env).

Place search for the brand's retail/service presence in the market, then reviews for
each matched place. Places returns a capped sample of reviews (typically ~5 per place)
— this limitation is recorded in the export.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from scrapers.base import ScrapeResult

CHANNEL = "google_business"
FIND = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"


def _default_get(url: str, params: Dict[str, Any]):
    from http_client import get_session

    return get_session().get(url, params=params)


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
            *, get_fn: Optional[Callable[[str, Dict[str, Any]], Any]] = None) -> ScrapeResult:
    from settings import settings

    params = params or {}
    get = get_fn or _default_get
    result = ScrapeResult(CHANNEL)

    api_key = settings.places_api_key
    if not api_key:
        result.error("GOOGLE_PLACES_API_KEY not set — Google Business reviews skipped.")
        return result

    query = params.get("query") or cfg.get("source_plan", {}).get("google_business", {}).get("query", "")
    if not query:
        result.error("No Google Business search query configured.")
        return result

    try:
        resp = get(FIND, {"query": query, "key": api_key})
        if getattr(resp, "status_code", 200) >= 400:
            result.error(f"Places textsearch -> HTTP {resp.status_code}")
            return result
        data = resp.json()
    except Exception as exc:
        result.error(f"Places textsearch failed: {exc}")
        return result

    place_ids = [p.get("place_id") for p in data.get("results", []) if p.get("place_id")]
    max_places = int(params.get("max_places", 10))

    for pid in place_ids[:max_places]:
        try:
            dr = get(DETAILS, {"place_id": pid, "fields": "name,rating,reviews,formatted_address",
                               "key": api_key})
            if getattr(dr, "status_code", 200) >= 400:
                result.error(f"Places details {pid} -> HTTP {dr.status_code}")
                continue
            detail = dr.json().get("result", {})
        except Exception as exc:
            result.error(f"Places details failed ({pid}): {exc}")
            continue
        name = detail.get("name", "")
        for rev in detail.get("reviews", []) or []:
            result.add(
                {
                    "title": f"Google review: {name}",
                    "text": rev.get("text", ""),
                    "link": rev.get("author_url", "") or f"https://www.google.com/maps/place/?q=place_id:{pid}",
                    "published": _rel_iso(rev),
                    "extra": {"type": "google_review", "place": name, "place_id": pid,
                              "rating": rev.get("rating"), "address": detail.get("formatted_address", ""),
                              "sample_capped": True},
                }
            )
    return result


def _rel_iso(rev: Dict[str, Any]) -> str:
    ts = rev.get("time")
    if not ts:
        return ""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(ts), tz=timezone.utc).date().isoformat()
    except (ValueError, OSError, TypeError):
        return ""
