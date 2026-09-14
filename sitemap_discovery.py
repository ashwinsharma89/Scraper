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
_SITEMAP_ENTRY_RE = re.compile(r"<sitemap>(.*?)</sitemap>", re.IGNORECASE | re.DOTALL)
_URL_ENTRY_RE = re.compile(r"<url>(.*?)</url>", re.IGNORECASE | re.DOTALL)

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
    dependency for it.

    Real bug found live (Increment 9, writing the regression test for the sub-sitemap
    recency-sort fix): the previous version extracted ALL <loc> and ALL <lastmod>
    values from the whole document as two flat lists and zipped them by position. That
    silently mis-pairs entries the instant SOME entries in a document have <lastmod>
    and others don't (exactly thanhnien.vn's real shape -- category/utility
    sub-sitemaps have none, dated article sub-sitemaps do): an earlier entry with no
    lastmod would steal a LATER entry's lastmod value instead of getting None, shifting
    every date onto the wrong URL. Parsing <sitemap>...</sitemap> / <url>...</url> as
    individual blocks and matching <loc>/<lastmod> WITHIN each block pairs them
    correctly regardless of which entries have a lastmod at all.
    """
    xml_text = xml_text or ""
    blocks = _SITEMAP_ENTRY_RE.findall(xml_text) or _URL_ENTRY_RE.findall(xml_text)
    entries: List[Dict[str, Optional[str]]] = []
    for block in blocks:
        loc_m = _LOC_RE.search(block)
        if not loc_m:
            continue
        lastmod_m = _LASTMOD_RE.search(block)
        entries.append({"loc": loc_m.group(1), "lastmod": lastmod_m.group(1) if lastmod_m else None})
    return entries


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

    # Real bug found live (Increment/input #7, city-guide site discovery on India/
    # coffee: whatshot.in): the sitemap PROTOCOL says a sitemap-of-sitemaps must be
    # wrapped in a <sitemapindex> tag, but whatshot.in's real, live sitemap.xml wraps
    # its 171 sub-sitemap references (delhi-ncr-food-and-drinks.xml,
    # bangalore.xml, ...) in a plain <urlset> instead -- every entry's <loc> is
    # itself another .xml sitemap file, never a content page. The tag-name check
    # alone missed this entirely: raw_sitemap_urls=171, matched_keywords=0, because
    # every "url" actually WAS a sitemap that was never followed. Detected here as a
    # fallback: a <urlset> whose entries are ALL themselves .xml files (a real
    # content page essentially never ends in a literal ".xml") gets the exact same
    # follow-and-recency-sort treatment as a standard <sitemapindex>.
    is_sitemap_index = bool(_SITEMAPINDEX_RE.search(xml_text))
    if not is_sitemap_index and entries and all(
            e["loc"].split("?", 1)[0].split("#", 1)[0].lower().endswith(".xml") for e in entries):
        is_sitemap_index = True

    if is_sitemap_index:
        # Sort by lastmod (most recent first) before truncating to max_nested, rather
        # than trusting raw document order. Real gap found live (Increment 9,
        # generalization testing on electric scooters/Vietnam): thanhnien.vn's real
        # sitemap index lists categories-sitemap.xml, google-news-sitemap.xml, and
        # latest-news-sitemap.xml BEFORE any dated article sub-sitemap -- taking the
        # first 5 in document order followed category/utility pages instead of recent
        # articles, so real keyword matching against article URLs found nothing at all
        # despite the site genuinely having thousands of indexed pages. Entries with no
        # lastmod (typically category/utility sitemaps, not date-based article
        # listings) sort last, since there's no way to know how fresh their content is.
        def _recency_key(e):
            lm = e.get("lastmod")
            return (1, lm) if lm else (0, "")

        entries = sorted(entries, key=_recency_key, reverse=True)

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
