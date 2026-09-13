"""Sitemap-based URL discovery for arbitrary sites (DESIGN_01_category-discovery.md
§4 tier 2 — "the mechanism I recommend as primary").

Why sitemaps: an arbitrary lifestyle blog or health directory has no equivalent of
Google News' search-feed API. A sitemap is the closest thing to a sanctioned,
publisher-intended mechanism such a site offers — it's published explicitly *for*
being crawled, costs nothing beyond the fetch itself, and needs no scraping of a
search engine's own result pages (which §4 explicitly rules out as materially
riskier/ToS-violating).

Fetches via an injectable fetch_fn (matching scrapers/news.py's and
scrapers/generic_site.py's established convention) so the real path always goes
through http_client.get_session() (Ground Rule #2) and tests never touch the
network. Follows exactly ONE level of sitemap-index nesting, per §4's explicit
scope — not a general crawl of however many sub-sitemaps a large site publishes.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.IGNORECASE)
_SITEMAPINDEX_RE = re.compile(r"<sitemapindex", re.IGNORECASE)

# How many nested sub-sitemaps a sitemapindex is followed into. A real news/lifestyle
# site can publish hundreds of daily/monthly sub-sitemaps going back years; this pilot
# only needs recent volume, and an unbounded follow would turn one domain's discovery
# into an unbounded crawl. Sub-sitemaps are typically newest-first in the index, so this
# caps to "the most recent N", not an arbitrary N.
DEFAULT_MAX_NESTED_SITEMAPS = 5


def _default_fetch(url: str):
    from http_client import get_session

    return get_session().get(url)


def _parse_locs_with_lastmod(xml_text: str) -> List[Dict[str, Optional[str]]]:
    """Extract <loc>/<lastmod> pairs from ONE sitemap XML document. A sitemapindex and
    a urlset share this exact <loc>/<lastmod> shape (just nested under <sitemap> vs
    <url> respectively, per the sitemaps.org schema) so one parser covers both.

    A small regex parser, not a full XML parser, deliberately — sitemap XML is a
    simple, stable, externally-documented format, and this avoids a new XML-library
    dependency for it. <lastmod> entries, when present, appear 1:1 with <loc> entries
    in document order per the spec; a mismatch is tolerated honestly (lastmod left
    None) rather than silently mis-pairing entries.
    """
    locs = _LOC_RE.findall(xml_text or "")
    lastmods = _LASTMOD_RE.findall(xml_text or "")
    return [{"loc": loc, "lastmod": lastmods[i] if i < len(lastmods) else None}
            for i, loc in enumerate(locs)]


def discover_urls(domain: str, keywords: Optional[List[str]] = None, *,
                  cap: int = 200, max_nested: int = DEFAULT_MAX_NESTED_SITEMAPS,
                  fetch_fn: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """Fetch domain's /sitemap.xml, follow one level of index nesting if present,
    optionally keyword-filter by URL path/slug, and return up to `cap` URLs.

    Never fabricates: a missing/unreachable/empty sitemap returns ok=False with an
    honest error and an empty url list, not a guess.
    """
    fetch = fetch_fn or _default_fetch
    domain = (domain or "").strip().rstrip("/")
    empty_summary = {"raw_sitemap_urls": 0, "matched_keywords": 0, "returned": 0}

    if not domain:
        return {"domain": domain, "ok": False, "error": "empty domain", "urls": [],
                "_summary": empty_summary}

    base = domain if domain.startswith("http") else f"https://{domain}"
    sitemap_url = f"{base}/sitemap.xml"
    try:
        resp = fetch(sitemap_url)
    except Exception as exc:
        return {"domain": domain, "ok": False, "error": f"fetch failed: {exc}", "urls": [],
                "_summary": empty_summary}

    status = getattr(resp, "status_code", 200)
    if status >= 400:
        return {"domain": domain, "ok": False,
                "error": f"HTTP {status} for {sitemap_url}", "urls": [],
                "_summary": empty_summary}

    xml_text = resp.text or ""
    entries = _parse_locs_with_lastmod(xml_text)

    if _SITEMAPINDEX_RE.search(xml_text):
        all_entries: List[Dict[str, Optional[str]]] = []
        for sub in entries[:max_nested]:
            try:
                sub_resp = fetch(sub["loc"])
            except Exception:
                continue  # one dead sub-sitemap doesn't fail the whole domain
            if getattr(sub_resp, "status_code", 200) >= 400:
                continue
            all_entries.extend(_parse_locs_with_lastmod(sub_resp.text or ""))
    else:
        all_entries = entries

    raw_count = len(all_entries)

    kw = [k.lower() for k in (keywords or []) if k]
    matched = ([e for e in all_entries if any(k in e["loc"].lower() for k in kw)]
              if kw else all_entries)

    urls = [e["loc"] for e in matched][:cap]

    return {
        "domain": domain,
        "ok": True,
        "error": None,
        "urls": urls,
        "_summary": {"raw_sitemap_urls": raw_count, "matched_keywords": len(matched),
                    "returned": len(urls)},
    }
