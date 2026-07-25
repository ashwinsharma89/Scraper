"""YouTube collection via the official Data API v3 (key from env).

Search by regionCode / relevanceLanguage from config, within a publishedAfter/Before
window, then pull full comment threads. Quota-aware: stops and logs when the API
returns a quota error rather than silently truncating.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from scrapers.base import ScrapeResult, relevance_terms

CHANNEL = "youtube"
SEARCH = "https://www.googleapis.com/youtube/v3/search"
COMMENTS = "https://www.googleapis.com/youtube/v3/commentThreads"


def _default_get(url: str, params: Dict[str, Any]):
    from http_client import get_session

    return get_session().get(url, params=params)


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
            *, get_fn: Optional[Callable[[str, Dict[str, Any]], Any]] = None) -> ScrapeResult:
    from settings import settings

    params = params or {}
    get = get_fn or _default_get
    result = ScrapeResult(CHANNEL)

    api_key = settings.youtube_api_key
    if not api_key:
        result.error("YOUTUBE_API_KEY not set — YouTube collection skipped (no data fabricated).")
        return result

    yt = cfg.get("source_plan", {}).get("youtube", {})
    region = yt.get("region_code", "")
    rel_lang = yt.get("relevance_language", "")
    terms = relevance_terms(cfg)
    query = " OR ".join(terms) if terms else cfg.get("product", {}).get("brand", "")
    if not query:
        result.error("No query terms for YouTube search.")
        return result

    today = date.today()
    after = params.get("start_date") or (today - timedelta(days=180)).isoformat()
    before = params.get("end_date") or today.isoformat()
    max_videos = int(params.get("max_videos", 25))

    search_params = {
        "part": "snippet", "q": query, "type": "video", "maxResults": min(max_videos, 50),
        "key": api_key, "order": "relevance",
        "publishedAfter": f"{after}T00:00:00Z", "publishedBefore": f"{before}T23:59:59Z",
    }
    if region:
        search_params["regionCode"] = region
    if rel_lang:
        search_params["relevanceLanguage"] = rel_lang

    try:
        resp = get(SEARCH, search_params)
        if getattr(resp, "status_code", 200) >= 400:
            result.error(f"YouTube search -> HTTP {resp.status_code}: {getattr(resp, 'text', '')[:200]}")
            return result
        data = resp.json()
    except Exception as exc:
        result.error(f"YouTube search failed: {exc}")
        return result

    video_ids: List[str] = []
    for it in data.get("items", []):
        vid = it.get("id", {}).get("videoId")
        sn = it.get("snippet", {})
        if vid:
            video_ids.append(vid)
            result.add(
                {
                    "title": sn.get("title", ""),
                    "text": sn.get("description", ""),
                    "link": f"https://www.youtube.com/watch?v={vid}",
                    "published": (sn.get("publishedAt", "") or "")[:10],
                    "extra": {"type": "video", "channel": sn.get("channelTitle", ""), "video_id": vid},
                }
            )

    # Comment threads per video (quota-aware).
    for vid in video_ids:
        page_token = None
        while True:
            cparams = {"part": "snippet", "videoId": vid, "maxResults": 100,
                       "textFormat": "plainText", "key": api_key}
            if page_token:
                cparams["pageToken"] = page_token
            try:
                cr = get(COMMENTS, cparams)
                if getattr(cr, "status_code", 200) == 403:
                    result.error(f"YouTube comments quota/permission error on {vid}; stopping.")
                    return result
                if getattr(cr, "status_code", 200) >= 400:
                    result.error(f"YouTube comments {vid} -> HTTP {cr.status_code}")
                    break
                cdata = cr.json()
            except Exception as exc:
                result.error(f"YouTube comments failed ({vid}): {exc}")
                break
            for th in cdata.get("items", []):
                top = th.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                body = top.get("textDisplay", "")
                if body:
                    result.add(
                        {
                            "title": f"YouTube comment ({vid})",
                            "text": body,
                            "link": f"https://www.youtube.com/watch?v={vid}",
                            "published": (top.get("publishedAt", "") or "")[:10],
                            "extra": {"type": "comment", "video_id": vid,
                                      "likes": top.get("likeCount", 0)},
                        }
                    )
            page_token = cdata.get("nextPageToken")
            if not page_token:
                break
    return result
