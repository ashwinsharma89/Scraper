"""Market Intelligence — the cited (human-entered) layer + Manual Intelligence workflows.

Two human-entry surfaces, both persisted to the ``market_intel`` table:

  1. Cited desk-research entries (market size/CAGR, share, GDP, demographics, sentiment,
     regulation, entry barriers). Citation discipline is ENFORCED by the tool: value,
     source name, source URL, publication date, accessed date, and confidence are all
     required. There is NO auto-scraping of paywalled research here.

  2. Manual Intelligence (Tier-2): assisted-manual ad-library research. The tool
     generates per-platform checklists with deep links pre-built from the project's
     brand/competitor names, and stores structured ad observations with attribution.
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

import storage

# Cited-layer categories (a helpful, editable taxonomy — not brand-specific).
CITED_CATEGORIES = [
    "Market size", "Market CAGR / growth", "Competitor market share", "GDP",
    "Category share of GDP / spend", "Demographic split (age)", "Demographic split (city/region)",
    "Economic sentiment", "Regulation", "Entry barriers", "Other",
]

CONFIDENCE_LEVELS = ["high", "medium", "low"]

REQUIRED_CITED_FIELDS = ["value", "source_name", "source_url", "publication_date",
                         "accessed_date", "confidence"]


def add_cited_entry(project_id: int, entry: Dict[str, Any], entered_by: Optional[str] = None) -> int:
    """Add a cited desk-research entry, enforcing full citation discipline.

    Raises ValueError listing every missing required field, so the UI/API can surface
    exactly what the analyst must supply. Nothing partial is ever stored.
    """
    missing = [f for f in REQUIRED_CITED_FIELDS if not str(entry.get(f, "")).strip()]
    if missing:
        raise ValueError(f"Cited entry missing required fields: {', '.join(missing)}")
    conf = str(entry.get("confidence", "")).strip().lower()
    if conf not in CONFIDENCE_LEVELS:
        raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}")

    payload = {
        "entry_type": "cited",
        "category": entry.get("category", "Other"),
        "metric": entry.get("metric", ""),
        "value": entry.get("value"),
        "source_name": entry.get("source_name"),
        "source_url": entry.get("source_url"),
        "publication_date": entry.get("publication_date"),
        "accessed_date": entry.get("accessed_date"),
        "confidence": conf,
        "notes": entry.get("notes", ""),
        "extra": entry.get("extra", {}),
    }
    intel_id = storage.add_market_intel(project_id, payload, entered_by=entered_by)
    storage.audit("market_intel.cited.add", f"{payload['category']}: {payload['metric']}",
                  acting_user=entered_by, project_id=project_id)
    return intel_id


def add_manual_ad(project_id: int, entry: Dict[str, Any], entered_by: Optional[str] = None) -> int:
    """Add a Manual Intelligence ad observation (Tier-2)."""
    if not str(entry.get("advertiser", "")).strip() or not str(entry.get("platform", "")).strip():
        raise ValueError("Manual ad entry requires at least 'advertiser' and 'platform'.")
    payload = {
        "entry_type": "manual_ad",
        "category": "Advertising",
        "metric": entry.get("creative_theme", ""),
        "value": entry.get("advertiser"),
        "source_name": entry.get("platform"),
        "source_url": entry.get("source_url", ""),
        "publication_date": entry.get("first_seen_date", ""),
        "accessed_date": entry.get("accessed_date", ""),
        "confidence": entry.get("confidence", "medium"),
        "notes": entry.get("notes", ""),
        "extra": {
            "creative_theme": entry.get("creative_theme", ""),
            "format": entry.get("format", ""),
            "first_seen_date": entry.get("first_seen_date", ""),
            "screenshot_path": entry.get("screenshot_path", ""),
        },
    }
    intel_id = storage.add_market_intel(project_id, payload, entered_by=entered_by)
    storage.audit("market_intel.manual_ad.add",
                  f"{payload['source_name']}: {payload['value']}", acting_user=entered_by,
                  project_id=project_id)
    return intel_id


def list_cited(project_id: int) -> List[Dict[str, Any]]:
    return storage.list_market_intel(project_id, entry_type="cited")


def list_manual_ads(project_id: int) -> List[Dict[str, Any]]:
    return storage.list_market_intel(project_id, entry_type="manual_ad")


# --------------------------------------------------------------------------- #
# Manual Intelligence checklist + deep links
# --------------------------------------------------------------------------- #
def _q(s: str) -> str:
    return urllib.parse.quote_plus(s or "")


def _deep_links(platform_key: str, name: str, country_code: str) -> Optional[str]:
    cc = (country_code or "").upper()
    if not name:
        return None
    if platform_key == "meta_ad_library":
        return (f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all"
                f"&country={cc or 'ALL'}&q={_q(name)}&search_type=keyword_unordered")
    if platform_key == "google_ads_transparency":
        return f"https://adstransparency.google.com/?region={cc or 'anywhere'}&query={_q(name)}"
    if platform_key == "tiktok_creative_center":
        return ("https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en"
                f"?region={cc}")  # advertiser search is in-page; region deep-linked
    if platform_key == "twitter_x":
        return f"https://twitter.com/search?q={_q(name)}&f=live"
    return None


def manual_intelligence_plan(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-platform checklist with deep links for brand + each competitor."""
    brand = cfg.get("product", {}).get("brand", "")
    competitors = cfg.get("competitors", [])
    cc = cfg.get("market", {}).get("country_code", "")
    platforms = cfg.get("source_plan", {}).get("manual_intelligence_platforms", [])

    names = ([brand] if brand else []) + list(competitors)
    plan = []
    for p in platforms:
        key = p.get("key")
        links = []
        if p.get("supports_name_search"):
            for name in names:
                url = _deep_links(key, name, cc)
                if url:
                    links.append({"name": name, "url": url})
        plan.append({
            "key": key,
            "name": p.get("name"),
            "note": p.get("note", ""),
            "supports_api_key": p.get("supports_api_key", False),
            "supports_name_search": p.get("supports_name_search", False),
            "deep_links": links,
            "checklist": [
                f"Open each deep link and record ads observed for {', '.join(names) or 'the brand'}.",
                "For each ad: advertiser, creative theme, format, first-seen date, screenshot, notes.",
                "Save observations via the Manual Intelligence entry form (attributed to you).",
            ],
        })
    return plan
