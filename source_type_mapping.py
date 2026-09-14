"""Category → source-type mapping, two layers (DESIGN_01_category-discovery.md §2).

Layer 1 (open, LLM-driven): given a classified category + geo-scope, ask the model
for real, NAMED source-type categories relevant to this vertical — "lifestyle & food
blogs," "café/venue listing sites," "healthcare directories," etc. Same suggestion-
then-confirm shape as every other module here; genuinely extensible, no code change
needed for a new vertical to produce a sensible list.

Layer 2 (closed, code-level routing): whatever Layer 1 names, the ACTUAL fetch
mechanism this tool can execute is one of a small, finite set — the same way
scrapers/__init__.py's _REGISTRY (10 named channels) is a legitimate closed set of
*implemented mechanisms*, not a hardcoded claim about the world. §2 recommends
starting with a cheap keyword match rather than a second LLM call, since this
routing decision is low-stakes and easy to get right mechanically — only escalate
to a model call if that proves unreliable, which nothing here has evidence of yet.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

CAP = 8

# Keyword -> existing channel key. A suggested source-type name matching any keyword
# here routes to that channel unchanged (scrapers.get_scraper() picks it up exactly
# as it does today); everything else routes to generic_site_discovery (§4/§5).
# image_analysis excluded deliberately -- it's a derived post-processing step over
# e-commerce images, not something Layer 1 would ever independently suggest as a
# "source type to find."
_CHANNEL_KEYWORDS: Dict[str, List[str]] = {
    "news": ["news"],
    "reddit": ["reddit"],
    "forums": ["forum"],
    # Bare "video" removed: a real bug found via Increment 9 generalization testing
    # (electric scooters/Vietnam) -- "TikTok & short-form video platforms" matched
    # "video" and routed to the YouTube channel, even though TikTok content has no
    # YouTube Data API applicability at all, and "tiktok" itself is a genuine Tier-3
    # keyword that this generic match was silently overriding (existing-channel checks
    # run before Tier-3, per route_source_type). "video" alone is inherently ambiguous
    # -- it could mean YouTube, TikTok, Instagram Reels, or Vimeo -- so only the
    # unambiguous "youtube" keyword should claim this channel.
    "youtube": ["youtube"],
    "trends": ["google trends", "search trend", "search interest"],
    "google_business": ["google business", "google review", "place review", "business review"],
    "quora": ["quora"],
    "ecommerce": ["e-commerce", "ecommerce", "marketplace", "product listing", "online shopping"],
    "gdelt": ["gdelt"],
}

# CLAUDE.md's own documented, permanent Tier-3 gaps: "Quick-commerce & most social are
# app-only / anti-automation → Tier-3 gaps, never scrapers." A suggested source-type
# naming one of these must NOT fall through to generic_site_discovery — that pipeline
# fetches sitemap-published web pages, which these platforms fundamentally don't
# expose (there is no public sitemap of individual Instagram posts or WhatsApp group
# messages). Silently routing them there wouldn't fabricate data, but it WOULD let a
# wizard confirm a source type that can only ever silently find nothing — the honest
# thing is to say so up front, not let the pipeline discover it the hard way.
# A bare platform name, not a fixed phrase like "facebook group" -- found live via
# Increment 9 generalization testing (skincare/Brazil): Layer 1 phrased it as
# "Facebook beauty & skincare groups & communities", which "facebook group" as a
# contiguous phrase never matches, so it silently fell through to
# generic_site_discovery (a pipeline that can never work for a login-walled Facebook
# group). Matching "facebook" alone, the same way instagram/whatsapp/telegram/tiktok
# already do, catches every real phrasing Layer 1 produces. No regression risk: a
# genuine existing-channel mention (e.g. "YouTube and Facebook video content") still
# matches its channel keyword FIRST (channels are checked before Tier-3, see
# route_source_type), so this can only ever narrow generic_site_discovery, never a
# real channel.
_TIER3_KEYWORDS: List[str] = [
    "instagram", "whatsapp", "telegram", "tiktok", "facebook",
    "snapchat", "wechat", "line app",
]


def route_source_type(name: str) -> Dict[str, Optional[str]]:
    """Layer 2. Returns {"strategy": "existing_channel"|"generic_site_discovery"|
    "unsupported", "channel": <key>|None}.

    Real gap found and fixed (user feedback: "don't need whatsapp groups but need
    forums"): a compound Layer-1 suggestion naming BOTH a real, buildable channel and
    a Tier-3 platform in the same string — e.g. "Niche coffee forums & WhatsApp
    groups" — used to check Tier-3 first and lose the whole suggestion, including the
    genuinely real forums coverage. Existing-channel keywords are checked FIRST now:
    a real, working capability in the name wins over an unsupported one mentioned
    alongside it, rather than an all-or-nothing veto. A name naming ONLY Tier-3
    platforms (no channel keyword at all) is still correctly flagged unsupported.
    """
    low = (name or "").strip().lower()
    for channel, keywords in _CHANNEL_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return {"strategy": "existing_channel", "channel": channel}
    if any(kw in low for kw in _TIER3_KEYWORDS):
        return {"strategy": "unsupported", "channel": None}
    return {"strategy": "generic_site_discovery", "channel": None}


def build_prompt(category: str, geo_scope: Optional[Dict[str, Any]] = None) -> str:
    geo_scope = geo_scope or {}
    level = geo_scope.get("level", "")
    value = geo_scope.get("value", "")
    country = geo_scope.get("country", "")
    where = f"{value} ({level}, {country})" if value and level else (country or "an unspecified market")

    return "\n".join([
        f'Name the REAL kinds of online sources that would together give good coverage of the '
        f'category "{category}" in {where} — think broadly: news, social discussion, review/'
        f"directory sites, lifestyle or vertical-specific blogs, forums, video, "
        "city/regional guide platforms (e.g. a city-guide brand with separate editions per "
        "major city — LBB, So.city, Whatshot are real examples in India; most markets have "
        "an equivalent), anything genuinely relevant, not just one type.",
        "",
        "Return ONLY a JSON object with this key:",
        '  "source_types": [ {"name": "<short real source-type name, e.g. \\"lifestyle & food '
        'blogs\\">", "why": "<one short reason it matters for this category/market>"} ] — up to '
        f"{CAP}, most important first",
        "",
        "Rules:",
        "- Name genuine categories of source, not individual site names.",
        "- No commentary outside the JSON.",
    ])


def parse_source_types(text: str) -> List[Dict[str, str]]:
    if not text:
        raise ValueError("Empty model response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object in model response")
    data = json.loads(text[start:end + 1])
    out: List[Dict[str, str]] = []
    seen = set()
    for st in (data.get("source_types") or [])[:CAP]:
        name = (st.get("name") or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append({"name": name, "why": st.get("why", "")})
    return out


def suggest_source_types(category: str, geo_scope: Optional[Dict[str, Any]] = None,
                         call_fn: Optional[Callable[[str, str], str]] = None,
                         model: Optional[str] = None) -> Dict[str, Any]:
    """Layer 1 + Layer 2 combined: each suggested source type comes back already
    routed, so the wizard can show the human both "what" and "how it would be
    fetched" in one confirmation step."""
    from settings import settings

    category = (category or "").strip()
    if not category:
        raise ValueError("category is required")

    call = call_fn or (lambda p, m: __import__("analysis").call_claude(p, m, max_tokens=1200))
    prompt = build_prompt(category, geo_scope)
    raw = call(prompt, model or settings.analysis_model)
    source_types = parse_source_types(raw)

    for st in source_types:
        st.update(route_source_type(st["name"]))

    return {
        "category": category,
        "source_types": source_types,
        "_summary": {
            "total": len(source_types),
            "existing_channel": sum(1 for s in source_types if s["strategy"] == "existing_channel"),
            "generic_site_discovery": sum(1 for s in source_types
                                          if s["strategy"] == "generic_site_discovery"),
            "unsupported": sum(1 for s in source_types if s["strategy"] == "unsupported"),
        },
    }
