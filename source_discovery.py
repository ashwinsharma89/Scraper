"""AI-assisted source discovery, with honest validation.

Given a project's market + category + brand + competitors, ask Claude to propose REAL
candidate sources per channel (news RSS, e-commerce search URLs, forums, subreddits,
quick-commerce platforms). Every candidate is then VALIDATED by the tool — RSS via the
feed-health check, web URLs via a reachability probe — and returned with a status so the
user confirms before anything is added to the source plan.

This is a suggestion+validation layer, not an oracle: LLM-proposed URLs can be wrong or
dead, which is exactly why nothing is auto-trusted. App-only platforms are surfaced as
Tier-3 gaps, never as scrapable sources.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

# Per-channel caps so validation stays quick and the list stays reviewable.
CAP = 15


def build_prompt(cfg: Dict[str, Any]) -> str:
    market = cfg.get("market", {})
    product = cfg.get("product", {})
    country = market.get("country", "")
    languages = ", ".join(market.get("languages", []) or [])
    brand = product.get("brand", "")
    category = product.get("category", "")
    ctype = product.get("category_type", "")
    competitors = ", ".join(cfg.get("competitors", []) or [])

    return "\n".join([
        f"You are configuring market-research data sources for a study of the product "
        f"\"{brand}\" (category: {category}; type: {ctype}) in the market: {country}. "
        f"Relevant languages: {languages}. Competitors: {competitors or '(none given)'}.",
        "",
        "Propose REAL, well-known sources that actually exist in this market. Do NOT invent "
        "URLs or brands. If unsure of an exact path, give the platform's real base domain. "
        "Prefer the biggest / most relevant sources. Keep to about the top 15 per channel.",
        "",
        "Return ONLY a JSON object with these keys:",
        '  "news_rss": [ {"home": "<homepage URL of a real news outlet in this market>", '
        '"url": "<its RSS feed URL if you know it, else \\"\\">", "outlet": "<name>", '
        '"why": "<short reason>"} ]',
        '  "ecommerce": [ {"url": "<a SEARCH URL on a real marketplace in this market, with the '
        f'brand \\"{brand}\\" as the query>", "platform": "<name>", "why": "<reason>"}} ]',
        '  "forums": [ {"url": "<a real discussion forum URL relevant to the category/market>", '
        '"name": "<name>", "why": "<reason>"} ]',
        '  "subreddits": [ "<subreddit name without r/>", ... ]',
        '  "quick_commerce": [ {"platform": "<name>", "web_scrapable": true|false, '
        '"url": "<web URL if any>", "note": "<why; if app-only, say so>"} ]',
        '  "social_note": "<one line: which social platforms matter here and that they are '
        'manual/Tier-3, not scraped>"',
        "",
        "Rules:",
        "- e-commerce URLs MUST be search URLs that include the brand as the query term.",
        "- Mark any app-only quick-commerce/delivery platform web_scrapable=false (it becomes a "
        "documented gap, not a scraper).",
        "- Only include sources genuinely present in this market.",
        "- No commentary outside the JSON.",
    ])


def parse_suggestions(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("Empty model response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object in model response")
    data = json.loads(text[start:end + 1])
    return {
        "news_rss": (data.get("news_rss") or [])[:CAP],
        "ecommerce": (data.get("ecommerce") or [])[:CAP],
        "forums": (data.get("forums") or [])[:CAP],
        "subreddits": [s for s in (data.get("subreddits") or []) if s][:CAP],
        "quick_commerce": (data.get("quick_commerce") or [])[:CAP],
        "social_note": data.get("social_note", ""),
    }


def discover_feed(home_url: str, fetch=None) -> Optional[str]:
    """RSS autodiscovery: fetch an outlet's homepage and read the real feed URL from its
    ``<link rel="alternate" type="...rss/atom...">`` tag. Reliable because the URL comes
    from the site's own HTML, not an LLM guess."""
    from urllib.parse import urljoin

    from bs4 import BeautifulSoup

    if fetch is None:
        from http_client import get_session
        fetch = lambda u: get_session().get(u, rate_delay=0.3, timeout=8, allow_redirects=True)
    try:
        resp = fetch(home_url)
        if getattr(resp, "status_code", 200) >= 400:
            return None
        soup = BeautifulSoup(getattr(resp, "text", "") or "", "html.parser")
    except Exception:
        return None
    for link in soup.find_all("link"):
        rel = " ".join(link.get("rel", []) or []).lower()
        typ = (link.get("type", "") or "").lower()
        if ("alternate" in rel or not rel) and ("rss" in typ or "atom" in typ or "xml" in typ):
            href = link.get("href")
            if href:
                return urljoin(home_url, href)
    return None


def _probe(url: str) -> Dict[str, Any]:
    """Reachability probe. A response (even 403) means the domain is real; only a
    connection/DNS failure means dead."""
    from http_client import get_session

    out = {"reachable": False, "status": None, "note": None}
    try:
        resp = get_session().get(url, rate_delay=0.3, timeout=8, allow_redirects=True)
        out["status"] = resp.status_code
        out["reachable"] = True  # got an HTTP response
        if resp.status_code in (401, 403, 405, 429):
            out["note"] = f"HTTP {resp.status_code} (site up but may block bots)"
        elif resp.status_code >= 400:
            out["note"] = f"HTTP {resp.status_code}"
    except Exception as exc:
        out["note"] = f"{type(exc).__name__} (unreachable)"
    return out


def validate(suggestions: Dict[str, Any]) -> Dict[str, Any]:
    """Attach validation status to each candidate. RSS uses the feed-health check."""
    import config as config_mod

    # News RSS -> feed health, with autodiscovery fallback from the outlet homepage.
    rss_urls = [c.get("url") for c in suggestions["news_rss"] if c.get("url")]
    health = {h["url"]: h for h in config_mod.feed_health_check(rss_urls)} if rss_urls else {}
    for c in suggestions["news_rss"]:
        h = health.get(c.get("url"), {})
        if h.get("healthy"):
            c["valid"] = True
            c["status"] = h.get("status")
            c["note"] = None
            continue
        # Guessed feed URL was missing/dead -> try to discover the real one from the homepage.
        home = c.get("home") or c.get("url")
        discovered = discover_feed(home) if home else None
        if discovered:
            dh = config_mod.feed_health_check([discovered])
            if dh and dh[0].get("healthy"):
                c["url"] = discovered
                c["valid"] = True
                c["status"] = dh[0].get("status")
                c["note"] = "auto-discovered from homepage"
                continue
        c["valid"] = False
        c["status"] = h.get("status")
        c["note"] = (h.get("reason") or "no valid feed found") + " (autodiscovery failed)"

    # E-commerce + forums -> reachability probe.
    for key in ("ecommerce", "forums"):
        for c in suggestions[key]:
            if c.get("url"):
                p = _probe(c["url"])
                c["valid"] = p["reachable"]
                c["status"] = p["status"]
                c["note"] = p["note"]
            else:
                c["valid"] = False
                c["note"] = "no URL"

    # Subreddits and quick-commerce are passed through (subreddit existence is confirmed
    # when Reddit is actually run; quick-commerce app-only entries are gaps by design).
    return suggestions


def suggest_sources(cfg: Dict[str, Any], call_fn: Optional[Callable[[str, str], str]] = None,
                    do_validate: bool = True, model: Optional[str] = None) -> Dict[str, Any]:
    from settings import settings

    call = call_fn or (lambda p, m: __import__("analysis").call_claude(p, m, max_tokens=2000))
    prompt = build_prompt(cfg)
    raw = call(prompt, model or settings.analysis_model)
    suggestions = parse_suggestions(raw)
    if do_validate:
        suggestions = validate(suggestions)
    # Summary counts.
    suggestions["_summary"] = {
        "news_rss": len(suggestions["news_rss"]),
        "ecommerce": len(suggestions["ecommerce"]),
        "forums": len(suggestions["forums"]),
        "subreddits": len(suggestions["subreddits"]),
        "quick_commerce": len(suggestions["quick_commerce"]),
    }
    return suggestions
