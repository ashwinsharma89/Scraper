"""Channel registry.

Modules are imported lazily so that heavy optional deps (Playwright, anthropic,
pytrends, Pillow) are only required when that specific channel actually runs.
"""
from __future__ import annotations

import importlib
from typing import Dict, List

# channel key -> module name within this package
_REGISTRY: Dict[str, str] = {
    "ecommerce": "scrapers.ecommerce",
    "news": "scrapers.news",
    "gdelt": "scrapers.gdelt",
    "reddit": "scrapers.reddit",
    "forums": "scrapers.forums",
    "youtube": "scrapers.youtube",
    "trends": "scrapers.trends",
    "google_business": "scrapers.google_business",
    "quora": "scrapers.quora",
    "image_analysis": "scrapers.image_analysis",
}

# Human-facing metadata for the UI / methodology (no network needed to read this).
CHANNEL_INFO: Dict[str, Dict[str, str]] = {
    "ecommerce": {"tier": "1", "name": "E-commerce (Playwright)",
                  "method": "Rendered product/category/search pages; review text and internal "
                            "review XHR intercepted where detectable. Snapshot semantics — "
                            "scheduled repeats build price/review time series.",
                  "limitation": "ToS gray zone; internal research, low volume, read-only; proxy "
                                "recommended beyond light use. No historical backfill."},
    "news": {"tier": "1", "name": "News / RSS",
             "method": "Regular RSS + Google News search feeds with monthly/weekly chunking, "
                       "OR keyword filter, strict body-content relevance validation, and a "
                       "market gate that keeps only in-market outlets (by domain ccTLD / market "
                       "terms + demonym) so a Malaysia study isn't flooded with e.g. Indian "
                       "coverage. Google News items with no literal keyword match anywhere on "
                       "the page (not even boilerplate) are kept, not dropped, and left for "
                       "Claude's brand_focus tag to confirm during Analyze — catches paraphrased "
                       "mentions a keyword-only check would miss (confirmed footer-only/junk "
                       "matches are still always dropped at collection).",
             "limitation": "Regular RSS cannot reach back in time; only chunked Google News and "
                           "GDELT can. Google News obfuscates article URLs, so its item text is the "
                           "feed summary (title-level) — add direct publisher RSS feeds for full "
                           "first-paragraph body text."},
    "gdelt": {"tier": "1", "name": "GDELT (DOC 2.0)",
              "method": "sourcecountry from config, monthly chunking, 250 records/chunk.",
              "limitation": "Metadata only (title/link/date/outlet/language) — no article body."},
    "reddit": {"tier": "1", "name": "Reddit (public JSON)",
               "method": "Configured subreddits, multi-sort union (new/top/relevance/comments), "
                         "nested comments for top-N discussed posts, deleted/removed excluded.",
               "limitation": "Public JSON only, no API key; 429s handled gracefully (partial results kept)."},
    "forums": {"tier": "1", "name": "Forums (requests + BS4)",
               "method": "User-supplied thread/listing URLs; auto/CSS post containers; "
                         "multi-language next-page pagination; page cap.",
               "limitation": "Structure varies per forum; custom selector may be needed."},
    "youtube": {"tier": "1", "name": "YouTube (Data API v3)",
                "method": "Search by regionCode/relevanceLanguage, date window, full comment threads.",
                "limitation": "Requires API key; quota-limited."},
    "trends": {"tier": "1", "name": "Google Trends (pytrends)",
               "method": "Interest-over-time + related queries for config keywords, geo from config.",
               "limitation": "Relative index, not absolute volume; unofficial endpoint."},
    "google_business": {"tier": "1", "name": "Google Business reviews (Places API)",
                        "method": "Place search + reviews for the brand's retail/service presence.",
                        "limitation": "Requires API key; Places returns a capped sample of reviews."},
    "quora": {"tier": "1", "name": "Quora (best-effort)",
              "method": "Question-page scraping with the same strict relevance validation.",
              "limitation": "Frequently blocks automation; logged honestly when blocked."},
    "image_analysis": {"tier": "1", "name": "Image analysis (EXIF + Claude vision)",
                       "method": "EXIF via Pillow + Claude-vision reading of packaging/labels/claims/prices.",
                       "limitation": "Only runs on images already collected by the e-commerce channel."},
}


def get_scraper(channel: str):
    if channel not in _REGISTRY:
        raise KeyError(f"Unknown channel: {channel}")
    return importlib.import_module(_REGISTRY[channel])


def available_channels() -> List[str]:
    return list(_REGISTRY.keys())
