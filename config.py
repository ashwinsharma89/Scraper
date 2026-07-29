"""Project configuration and the intake wizard.

This module is the generalization mechanism of MarketLens. NOTHING here is hard-coded
to a brand, category, country, or language. Everything project-specific flows from the
intake the user provides; the wizard turns that intake into an editable ``config`` dict
(stored as JSON in the DB, exportable as YAML) and a market/category-adapted source plan.
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Reference tables (facts about the world, NOT about any product)
# --------------------------------------------------------------------------- #
# ISO 3166-1 alpha-2 (used for Google News gl/ceid, YouTube regionCode, Trends geo),
# best-effort GDELT sourcecountry codes (FIPS-derived; user-confirmable in wizard), and
# the demonym (nationality adjective). The demonym matters for the news market filter:
# many countries' demonym is NOT a substring of the country name (France -> French,
# Philippines -> Filipino, UK -> British, Netherlands -> Dutch), so an article that only
# says "the French government..." would silently fail an country-name-only substring
# check. Malaysia happens to work by luck (Malaysia -> Malaysian); most countries don't.
COUNTRY_TABLE: Dict[str, Dict[str, str]] = {
    "singapore": {"name": "Singapore", "iso": "SG", "gdelt": "SN", "demonym": "Singaporean"},
    "india": {"name": "India", "iso": "IN", "gdelt": "IN", "demonym": "Indian"},
    "united states": {"name": "United States", "iso": "US", "gdelt": "US", "demonym": "American"},
    "usa": {"name": "United States", "iso": "US", "gdelt": "US", "demonym": "American"},
    "united kingdom": {"name": "United Kingdom", "iso": "GB", "gdelt": "UK", "demonym": "British"},
    "uk": {"name": "United Kingdom", "iso": "GB", "gdelt": "UK", "demonym": "British"},
    "germany": {"name": "Germany", "iso": "DE", "gdelt": "GM", "demonym": "German"},
    "france": {"name": "France", "iso": "FR", "gdelt": "FR", "demonym": "French"},
    "japan": {"name": "Japan", "iso": "JP", "gdelt": "JA", "demonym": "Japanese"},
    "china": {"name": "China", "iso": "CN", "gdelt": "CH", "demonym": "Chinese"},
    "indonesia": {"name": "Indonesia", "iso": "ID", "gdelt": "ID", "demonym": "Indonesian"},
    "malaysia": {"name": "Malaysia", "iso": "MY", "gdelt": "MY", "demonym": "Malaysian"},
    "thailand": {"name": "Thailand", "iso": "TH", "gdelt": "TH", "demonym": "Thai"},
    "vietnam": {"name": "Vietnam", "iso": "VN", "gdelt": "VM", "demonym": "Vietnamese"},
    "philippines": {"name": "Philippines", "iso": "PH", "gdelt": "RP", "demonym": "Filipino"},
    "australia": {"name": "Australia", "iso": "AU", "gdelt": "AS", "demonym": "Australian"},
    "canada": {"name": "Canada", "iso": "CA", "gdelt": "CA", "demonym": "Canadian"},
    "brazil": {"name": "Brazil", "iso": "BR", "gdelt": "BR", "demonym": "Brazilian"},
    "mexico": {"name": "Mexico", "iso": "MX", "gdelt": "MX", "demonym": "Mexican"},
    "spain": {"name": "Spain", "iso": "ES", "gdelt": "SP", "demonym": "Spanish"},
    "italy": {"name": "Italy", "iso": "IT", "gdelt": "IT", "demonym": "Italian"},
    "netherlands": {"name": "Netherlands", "iso": "NL", "gdelt": "NL", "demonym": "Dutch"},
    "united arab emirates": {"name": "United Arab Emirates", "iso": "AE", "gdelt": "AE", "demonym": "Emirati"},
    "uae": {"name": "United Arab Emirates", "iso": "AE", "gdelt": "AE", "demonym": "Emirati"},
    "saudi arabia": {"name": "Saudi Arabia", "iso": "SA", "gdelt": "SA", "demonym": "Saudi"},
    "south africa": {"name": "South Africa", "iso": "ZA", "gdelt": "SF", "demonym": "South African"},
    "nigeria": {"name": "Nigeria", "iso": "NG", "gdelt": "NI", "demonym": "Nigerian"},
    "kenya": {"name": "Kenya", "iso": "KE", "gdelt": "KE", "demonym": "Kenyan"},
    "south korea": {"name": "South Korea", "iso": "KR", "gdelt": "KS", "demonym": "Korean"},
}

CATEGORY_TYPES = [
    "fmcg_food",
    "consumer_electronics",
    "fashion",
    "services",
    "b2b_industrial",
    "other",
]

# Which category types plausibly have delivery / quick-commerce distribution.
DELIVERY_APPLICABLE = {"fmcg_food"}

# Default "next page" labels per language for forum pagination. Editable per project.
FORUM_NEXT_LABELS: Dict[str, List[str]] = {
    "en": ["next", "next page", "older", "older posts", "»", ">"],
    "zh": ["下一页", "下一頁", "后页", "更多", "»"],
    "ms": ["seterusnya", "lama", "»"],
    "id": ["berikutnya", "selanjutnya", "lama", "»"],
    "ta": ["அடுத்து", "»"],
    "hi": ["अगला", "पुराने", "»"],
    "es": ["siguiente", "más antiguos", "»"],
    "fr": ["suivant", "plus anciens", "»"],
    "de": ["weiter", "nächste", "älter", "»"],
    "ja": ["次へ", "古い", "»"],
    "th": ["ถัดไป", "»"],
    "vi": ["tiếp", "kế tiếp", "cũ hơn", "»"],
    "pt": ["próximo", "mais antigos", "»"],
    "ar": ["التالي", "أقدم", "»"],
}


def resolve_country(country: str) -> Dict[str, str]:
    """Look up ISO + GDELT codes for a free-text country name.

    Falls back to a neutral placeholder when unknown, flagging that the user must
    confirm the codes rather than silently guessing.
    """
    key = (country or "").strip().lower()
    if key in COUNTRY_TABLE:
        return dict(COUNTRY_TABLE[key])
    # Unknown -> placeholder the user must fill. Never fabricate a code or a demonym.
    return {"name": country.strip() or "Unknown", "iso": "", "gdelt": "", "demonym": "",
            "needs_confirmation": "true"}


# --------------------------------------------------------------------------- #
# Google News search-feed URL builder
# --------------------------------------------------------------------------- #
def build_google_news_url(
    query_terms: List[str],
    language: str,
    country_iso: str,
    after: Optional[str] = None,
    before: Optional[str] = None,
) -> str:
    """Build a Google News RSS *search* feed URL.

    hl = ``<lang>-<COUNTRY>``, gl = ``<COUNTRY>``, ceid = ``<COUNTRY>:<lang>`` — the
    exact triple Google News requires to localize results. Multi-word terms are
    phrase-quoted for precision; terms are OR-combined. ``after``/``before`` inject
    Google's date operators (YYYY-MM-DD) so the news scraper can chunk time windows.
    """
    country_iso = (country_iso or "").upper()
    language = (language or "").lower()

    parts: List[str] = []
    for t in query_terms:
        t = (t or "").strip()
        if not t:
            continue
        parts.append(f'"{t}"' if " " in t else t)
    query = " OR ".join(parts) if parts else ""
    if after:
        query = f"{query} after:{after}".strip()
    if before:
        query = f"{query} before:{before}".strip()

    hl = f"{language}-{country_iso}" if country_iso else language
    ceid = f"{country_iso}:{language}" if country_iso else language
    q = urllib.parse.quote_plus(query)
    return (
        "https://news.google.com/rss/search?"
        f"q={q}&hl={hl}&gl={country_iso}&ceid={ceid}"
    )


def build_google_news_feeds(
    keywords_by_language: Dict[str, Dict[str, List[str]]],
    languages: List[str],
    country_iso: str,
) -> List[Dict[str, str]]:
    """One feed per (language, keyword-structure) that has terms."""
    feeds: List[Dict[str, str]] = []
    for lang in languages:
        lang_kw = keywords_by_language.get(lang, {})
        for structure, terms in lang_kw.items():
            terms = [t for t in (terms or []) if t and t.strip()]
            if not terms:
                continue
            feeds.append(
                {
                    "language": lang,
                    "structure": structure,
                    "query": " OR ".join(terms),
                    "url": build_google_news_url(terms, lang, country_iso),
                }
            )
    return feeds


# --------------------------------------------------------------------------- #
# Bing News search-feed URL builder — a SECOND, independent index
# --------------------------------------------------------------------------- #
# Structural gap: relying on Google News alone means anything GN's index misses is
# invisible to the tool. Bing News RSS needs no API key, is a genuinely different
# crawl/index (catches sources GN missed), and — unlike Google News — its outbound
# links are a normal, resolvable HTTP redirect chain (the destination is a plain query
# param), so the existing article-body/first-paragraph/market-filter machinery works on
# it with no special-casing. Trade-off: Bing News search has no public date-range
# operator, so unlike Google News it cannot be month-chunked for "full year" runs — it
# returns whatever it currently has indexed as most relevant, once per collection.
def build_bing_news_url(query_terms: List[str], market: str = "") -> str:
    """Build a Bing News RSS search URL. ``market`` is Bing's market code (e.g. 'en-MY')."""
    parts: List[str] = []
    for t in query_terms:
        t = (t or "").strip()
        if not t:
            continue
        parts.append(f'"{t}"' if " " in t else t)
    query = " OR ".join(parts) if parts else ""
    q = urllib.parse.quote_plus(query)
    url = f"https://www.bing.com/news/search?q={q}&format=RSS"
    if market:
        url += f"&setmkt={urllib.parse.quote_plus(market)}"
    return url


def build_bing_news_feeds(
    keywords_by_language: Dict[str, Dict[str, List[str]]],
    languages: List[str],
    country_iso: str,
) -> List[Dict[str, str]]:
    """One feed per (language, keyword-structure) that has terms — mirrors
    build_google_news_feeds so both indexes get the same keyword coverage."""
    feeds: List[Dict[str, str]] = []
    for lang in languages:
        lang_kw = keywords_by_language.get(lang, {})
        for structure, terms in lang_kw.items():
            terms = [t for t in (terms or []) if t and t.strip()]
            if not terms:
                continue
            market = f"{lang}-{country_iso.upper()}" if country_iso else lang
            feeds.append(
                {
                    "language": lang,
                    "structure": structure,
                    "query": " OR ".join(terms),
                    "url": build_bing_news_url(terms, market),
                }
            )
    return feeds


# --------------------------------------------------------------------------- #
# Subreddit / segment suggestions
# --------------------------------------------------------------------------- #
def suggest_subreddits(country_name: str, category_type: str) -> List[str]:
    """Suggest *candidate* subreddits from country + category patterns.

    These are patterns the user confirms — never assumed to exist. No brand names.
    """
    candidates: List[str] = []
    slug = (country_name or "").strip().lower().replace(" ", "")
    if slug:
        candidates.append(slug)  # e.g. r/singapore
        candidates.append(f"{slug}fire")  # finance communities are common
    category_patterns = {
        "fmcg_food": ["food", "Cooking", "grocery", "snacks"],
        "consumer_electronics": ["gadgets", "technology", "BuyItForLife"],
        "fashion": ["fashion", "malefashionadvice", "femalefashionadvice"],
        "services": ["reviews", "personalfinance"],
        "b2b_industrial": ["smallbusiness", "Entrepreneur"],
        "other": [],
    }
    candidates.extend(category_patterns.get(category_type, []))
    # De-dup preserving order.
    seen = set()
    out = []
    for c in candidates:
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def segment_applicability(category_type: str) -> Dict[str, bool]:
    return {
        "delivery_quick_commerce": category_type in DELIVERY_APPLICABLE,
        "consumer_commerce": category_type not in {"b2b_industrial"},
        "b2b_trade_press": category_type == "b2b_industrial",
    }


# --------------------------------------------------------------------------- #
# Keyword scaffolding suggestions (structures, never pre-filled with real brands)
# --------------------------------------------------------------------------- #
def suggest_keyword_structures(brand: str, competitors: List[str], category: str,
                               languages: List[str]) -> Dict[str, Dict[str, List[str]]]:
    """Produce empty-but-structured keyword slots per language.

    The brand/category the *user* typed at intake are used to seed the primary
    language's slots as a convenience; every other slot is left empty for the user
    to fill in native-language terms. No third-party real brand is ever pre-filled
    beyond the competitor names the user themselves supplied.
    """
    structures = ["brand", "brand_price", "category_generic", "brand_complaint"]
    by_lang: Dict[str, Dict[str, List[str]]] = {}
    for i, lang in enumerate(languages):
        slots: Dict[str, List[str]] = {s: [] for s in structures}
        if i == 0:
            # Seed only the first (primary) language from user-supplied intake.
            if brand:
                slots["brand"] = [brand]
                slots["brand_price"] = [f"{brand} price"]
                slots["brand_complaint"] = [f"{brand} problem"]
            if category:
                slots["category_generic"] = [category]
        by_lang[lang] = slots
    return by_lang


def derive_relevance_terms(brand: str, competitors: List[str], category: str) -> List[str]:
    """Relevance terms = brand + competitors + category tokens (user-editable)."""
    terms: List[str] = []
    if brand:
        terms.append(brand)
    terms.extend([c for c in competitors if c])
    for token in (category or "").replace("/", " ").replace(",", " ").split():
        if len(token) > 2:
            terms.append(token)
    # De-dup preserving order, case-insensitive.
    seen = set()
    out = []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


# --------------------------------------------------------------------------- #
# The wizard
# --------------------------------------------------------------------------- #
def run_wizard(intake: Dict[str, Any]) -> Dict[str, Any]:
    """Turn raw intake into a full, editable project config with a source plan.

    Expected intake keys (all user-provided, none brand-hard-coded in this module):
      market.country, market.languages[]
      product.brand, product.parent_company, product.category, product.category_type
      competitors[]
      keywords.by_language{lang:{structure:[...]}} (optional; wizard scaffolds if absent)
      keywords.trend_terms[] (optional)
    """
    market = intake.get("market", {})
    product = intake.get("product", {})
    competitors = [c for c in intake.get("competitors", []) if c]

    country_info = resolve_country(market.get("country", ""))
    iso = country_info.get("iso", "")
    languages = [l for l in market.get("languages", []) if l] or ["en"]

    brand = product.get("brand", "")
    parent = product.get("parent_company", "")
    category = product.get("category", "")
    category_type = product.get("category_type", "other")
    if category_type not in CATEGORY_TYPES:
        category_type = "other"

    # Keywords: use user-provided structures if any, else scaffold.
    kw_in = intake.get("keywords", {})
    by_language = kw_in.get("by_language") or suggest_keyword_structures(
        brand, competitors, category, languages
    )
    trend_terms = [t for t in kw_in.get("trend_terms", []) if t]

    relevance_terms = intake.get("relevance_terms") or derive_relevance_terms(brand, competitors, category)

    segments = segment_applicability(category_type)

    # Google Business search query is a template, not a hard-coded brand.
    gb_query = f"{brand} {country_info['name']}".strip() if brand else ""

    source_plan = {
        "google_news_feeds": build_google_news_feeds(by_language, languages, iso),
        # A second, independent index — catches sources Google News's index missed.
        # No date-chunking support (see build_bing_news_feeds docstring), so it
        # complements rather than replaces the chunkable Google News channel.
        "bing_news_feeds": build_bing_news_feeds(by_language, languages, iso),
        "gdelt": {"sourcecountry": country_info.get("gdelt", ""),
                  "needs_confirmation": country_info.get("needs_confirmation", "false")},
        "subreddits": suggest_subreddits(country_info["name"], category_type),
        "rss_feeds": [],           # user fills from local knowledge; feed-health-checked
        "ecommerce_urls": [],      # user fills: explicit product/category/search URLs
        "ecommerce_search": [],    # user fills: search-URL templates with {q}, e.g.
                                   #   https://shopee.com.my/search?keyword={q}
        "ecommerce_keywords": [],  # keywords for the templates; defaults to relevance terms
        "forum_urls": [],          # user fills: thread/listing URLs
        "quora_topics": [],        # user fills
        "youtube": {"region_code": iso, "relevance_language": languages[0] if languages else "en"},
        "trends": {"geo": iso, "keywords": trend_terms or relevance_terms[:5]},
        "google_business": {"query": gb_query},
        "segments": segments,
        "forum_next_labels": {l: FORUM_NEXT_LABELS.get(l, FORUM_NEXT_LABELS["en"]) for l in languages},
        "manual_intelligence_platforms": _manual_platforms(category_type),
        "tier3_gaps": TIER3_GAPS,
    }

    config = {
        "config_schema": 1,
        "market": {
            "country": country_info["name"],
            "country_code": iso,
            "gdelt_country": country_info.get("gdelt", ""),
            "languages": languages,
            # Used by the news market-gate to drop off-market results (e.g. Indian
            # coverage in a Malaysia study). Includes both the country name AND its
            # demonym — for most countries the demonym is NOT a substring of the name
            # (France -> French, Philippines -> Filipino, UK -> British), so relying on
            # the country name alone silently misses demonym-only mentions. Add
            # cities/regions in Source plan to sharpen further.
            "cctld": f".{iso.lower()}" if iso else "",
            "market_terms": [t for t in [country_info.get("name", ""), country_info.get("demonym", "")] if t],
        },
        "product": {
            "brand": brand,
            "parent_company": parent,
            "category": category,
            "category_type": category_type,
        },
        "competitors": competitors,
        "keywords": {
            "by_language": by_language,
            "trend_terms": trend_terms,
        },
        "relevance_terms": relevance_terms,
        "source_plan": source_plan,
        "collection_settings": {
            "politeness_delay_seconds": 1.5,
            "forum_page_cap": 10,
            "news_chunk": "monthly",
            "gdelt_chunk_size": 250,
            "market_filter": True,  # drop news items with no signal they're in-market
        },
    }
    return config


def _manual_platforms(category_type: str) -> List[Dict[str, Any]]:
    """Tier-2 assisted-manual platforms with per-platform config (deep-link support)."""
    base = [
        {"key": "meta_ad_library", "name": "Meta Ad Library", "supports_name_search": True,
         "note": "Meta's API excludes most non-EU commercial ads; browse manually."},
        {"key": "tiktok_creative_center", "name": "TikTok Creative Center / Ads Library",
         "supports_name_search": True, "note": "Free to browse, hostile to automation."},
        {"key": "google_ads_transparency", "name": "Google Ads Transparency Center",
         "supports_name_search": True, "note": "Advertiser search by name."},
        {"key": "twitter_x", "name": "Twitter/X", "supports_name_search": True,
         "note": "Optional third-party API key slot available.", "supports_api_key": True},
    ]
    return base


# Tier-3: documented gaps. Never scraped. Listed in every export's Methodology.
TIER3_GAPS: List[Dict[str, str]] = [
    {"platform": "Instagram", "reason": "Aggressive anti-automation; no lawful public API for research scraping."},
    {"platform": "Facebook pages/groups", "reason": "Login-walled, anti-automation; API excludes needed data."},
    {"platform": "LinkedIn", "reason": "ToS prohibits scraping; strong anti-automation."},
    {"platform": "WhatsApp", "reason": "End-to-end encrypted private messaging; not a public source."},
    {"platform": "TikTok (organic posts)", "reason": "No stable public API; anti-automation."},
    {"platform": "App-only delivery / quick-commerce", "reason": "Mobile-app-only, no scrapable web surface."},
]


# --------------------------------------------------------------------------- #
# Feed health check
# --------------------------------------------------------------------------- #
def feed_health_check(urls: List[str]) -> List[Dict[str, Any]]:
    """Validate each feed URL; report dead feeds. Network via the shared session.

    A feed is healthy only if it returns 2xx AND the body parses as a feed with at
    least a channel/title or one entry. Everything else is reported as dead with a
    reason — never silently dropped.
    """
    from http_client import get_session

    results: List[Dict[str, Any]] = []
    session = get_session()
    for url in urls:
        entry: Dict[str, Any] = {"url": url, "healthy": False, "status": None, "reason": None, "entries": 0}
        try:
            resp = session.get(url)
            entry["status"] = resp.status_code
            if resp.status_code >= 400:
                entry["reason"] = f"HTTP {resp.status_code}"
                results.append(entry)
                continue
            body = resp.text or ""
            parsed = _looks_like_feed(body)
            entry["entries"] = parsed["entries"]
            if parsed["ok"]:
                entry["healthy"] = True
            else:
                entry["reason"] = parsed["reason"]
        except Exception as exc:  # network error, DNS failure, timeout
            entry["reason"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)
    return results


def _looks_like_feed(body: str) -> Dict[str, Any]:
    """Lightweight feed validation without a hard feedparser dependency."""
    lowered = body.lower()
    if "<rss" not in lowered and "<feed" not in lowered and "<rdf" not in lowered:
        return {"ok": False, "reason": "Not an RSS/Atom feed", "entries": 0}
    # Count entries/items cheaply.
    n_items = lowered.count("<item")
    n_entries = lowered.count("<entry")
    total = n_items + n_entries
    has_channel = "<channel" in lowered or "<feed" in lowered
    if total == 0 and not has_channel:
        return {"ok": False, "reason": "Feed has no channel and no entries", "entries": 0}
    return {"ok": True, "reason": None, "entries": total}
