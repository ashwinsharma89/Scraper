"""AI-assisted local outlet discovery for the market-relevance filter.

Problem this closes: the news market gate (scrapers/news.py market_signal) recognizes an
outlet as "in-market" either by its ccTLD or by a market_term matching its name/text — but
most genuinely local outlets do NOT carry the country's name in their own brand (Scroll.in,
NDTV, ScoopWhoop, The Quint, Sportskeeda — vs. Times of India, Indian Express, which do).
Hand-typing a list of local outlet names per project (as a user did for one real project this
session — ~90 real Indian outlets spanning news, lifestyle, entertainment, business, tech,
sports, and regional blogs) works, but doesn't scale and doesn't generalize automatically to
a different country or language a study is later pointed at.

Same suggestion+validation posture as source_discovery.py/term_expansion.py: Claude proposes
REAL, well-known outlets for the study's actual market+languages, spanning a broad category
range (not just hard news), nothing is fabricated, and nothing is added to market_terms until
the user reviews and confirms via apply_outlets().

Safety note: scrapers/news.py's market_signal() now matches on word boundaries, not a raw
substring (a real bug this exact use case found live — "Digit", a genuine Indian tech outlet,
matched inside "digital"). That fix removes most false-positive risk at the matching layer.
This module adds a second, independent safety net at suggestion time: any candidate outlet
name that is a single word at or under CAUTION_LENGTH is flagged `caution: true` so the
review UI can default it to unchecked — a short, common-word-shaped name is still worth a
human's second look, word-boundary-safe or not (e.g. a short acronym that is ALSO a common
short word in the study's own language).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

CAP = 25  # each outlet is a verbose 5-field object; see MAX_TOKENS below for the sizing math
CAUTION_LENGTH = 6
# 25 outlets x ~80-100 tokens/object (name+domain+category+language+why+JSON punctuation),
# plus prompt/JSON overhead. Found live: an earlier CAP=40 with max_tokens=2500 truncated
# mid-response (confirmed by inspecting the raw completion — it cut off inside a "domain"
# field), which then failed to parse at all. Sized with real headroom this time, and
# parse_outlets() below is ALSO made resilient to truncation regardless, since a model
# response running long for other reasons (verbose "why" text, etc.) is still possible.
MAX_TOKENS = 3000


def build_prompt(cfg: Dict[str, Any]) -> str:
    market = cfg.get("market", {})
    country = market.get("country", "") or "an unspecified market"
    languages = [l for l in (market.get("languages") or []) if l] or ["en"]
    category = cfg.get("product", {}).get("category", "")

    return "\n".join([
        f"You are identifying REAL, well-known media outlets and publishers relevant to a "
        f"market-research study in {country}, covering the languages: {', '.join(languages)}"
        + (f", for the product category \"{category}\"" if category else "") + ".",
        "",
        "This is NOT limited to hard news or newspapers. Include real outlets across ALL of "
        "these categories, as applicable to this market: mainstream news, business/finance/"
        "startups, technology/gadgets, sports, lifestyle and entertainment, culture and youth "
        "blogs, city/regional publications, and — for each non-English language listed — real "
        "outlets that publish natively IN that language, not just English-language outlets "
        "based in this country.",
        "",
        "Return ONLY a JSON object with this key:",
        '  "outlets": [ {"name": "<the outlet\'s real, commonly-used display name>", '
        '"domain": "<its real base domain, e.g. \\"ndtv.com\\">", '
        '"category": "<one of: news, business, tech, sports, lifestyle, culture, regional>", '
        '"language": "<the language this outlet primarily publishes in, an ISO code from the '
        'list above>", "why": "<one short reason it\'s a real, relevant outlet in this '
        f'market>"}} ] — up to {CAP}, most well-known/highest-circulation first',
        "",
        "Rules:",
        "- Every outlet must be REAL and well-known in this market — do not invent names or "
        "guess at a domain you are not confident about.",
        "- Prefer outlets whose own name does NOT already obviously contain the country's "
        "name (that case is already handled elsewhere) — the useful ones here are outlets a "
        "reader would recognize as local without the country's name being in the brand.",
        "- No commentary outside the JSON.",
    ])


def _looks_risky(name: str) -> bool:
    """True if this candidate name is short/single-word enough that a human should look
    twice before trusting it as a market_term (see module docstring)."""
    n = (name or "").strip()
    return bool(n) and " " not in n and len(n) <= CAUTION_LENGTH


def _extract_balanced_objects(text: str) -> List[Dict[str, Any]]:
    """Try every '{' in the text as a possible object start and parse the substring up to
    its own matching '}', skipping any that fail. Used as a fallback when the whole
    response isn't valid JSON (e.g. cut off mid-object by a max_tokens limit) — this
    salvages every outlet that WAS completed before the cutoff instead of discarding all
    of them over one incomplete trailing object.

    Deliberately does NOT track depth globally from the start of the text — the very
    first '{' is the OUTER {"outlets": [...]} wrapper, which never closes in a truncated
    response, so a single global depth counter never returns to 0 and finds nothing
    (confirmed live: an earlier version of this function had exactly that bug and
    silently extracted zero objects from a genuinely-salvageable response). Instead, each
    '{' gets its OWN independent attempt at finding a match; one that runs off the end of
    the text without closing is simply skipped, and the next '{' (e.g. the first real
    outlet object) is tried on its own terms.
    """
    objects: List[Dict[str, Any]] = []
    n = len(text)
    i = 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        closed_at = None
        j = i
        while j < n:
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        closed_at = j
                        break
            j += 1
        if closed_at is not None:
            try:
                obj = json.loads(text[i:closed_at + 1])
                if isinstance(obj, dict) and "name" in obj:
                    objects.append(obj)
            except json.JSONDecodeError:
                pass  # malformed candidate — skip, don't fail the whole batch over it
        i += 1  # advance by 1, not past the close — lets a nested '{' be tried too
    return objects


def parse_outlets(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("Empty model response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object in model response")

    try:
        data = json.loads(text[start:end + 1])
        raw_outlets = data.get("outlets") or []
    except json.JSONDecodeError:
        # Whole response isn't valid JSON — most commonly a max_tokens cutoff mid-object.
        # Salvage whatever complete outlet objects exist rather than losing all of them.
        raw_outlets = _extract_balanced_objects(text)
        if not raw_outlets:
            raise ValueError("Model response was not valid JSON and no outlet objects "
                             "could be salvaged from it")

    outlets: List[Dict[str, Any]] = []
    seen_lower = set()
    for o in raw_outlets[:CAP]:
        if not isinstance(o, dict):
            continue
        name = str(o.get("name") or "").strip()
        if not name or name.lower() in seen_lower:
            continue
        seen_lower.add(name.lower())
        outlets.append({
            "name": name,
            "domain": str(o.get("domain") or "").strip(),
            "category": str(o.get("category") or "").strip(),
            "language": str(o.get("language") or "").strip(),
            "why": str(o.get("why") or "").strip(),
            "caution": _looks_risky(name),
        })
    return {"outlets": outlets}


def suggest_outlets(cfg: Dict[str, Any], call_fn: Optional[Callable[[str, str], str]] = None,
                    model: Optional[str] = None) -> Dict[str, Any]:
    """Ask Claude for real local outlets across categories for this project's market+
    languages. Returns candidates only — nothing is written to market_terms here; see
    apply_outlets()."""
    from settings import settings

    call = call_fn or (lambda p, m: __import__("analysis").call_claude(p, m, max_tokens=MAX_TOKENS))
    prompt = build_prompt(cfg)
    raw = call(prompt, model or settings.analysis_model)
    result = parse_outlets(raw)
    by_cat: Dict[str, int] = {}
    for o in result["outlets"]:
        by_cat[o["category"] or "other"] = by_cat.get(o["category"] or "other", 0) + 1
    result["_summary"] = {"total": len(result["outlets"]),
                          "caution": sum(1 for o in result["outlets"] if o["caution"]),
                          "by_category": by_cat}
    return result


def apply_outlets(cfg: Dict[str, Any], selected_names: List[str]) -> Dict[str, Any]:
    """Apply a user-CONFIRMED subset of suggest_outlets()'s output: each selected outlet
    name is added to market.market_terms (deduped, case-insensitive) so scrapers/news.py's
    market_signal() recognizes that outlet as in-market on its own, without requiring the
    country's name to appear in the article text.

    Returns a NEW config dict; does not mutate the input. Does not touch keyword structures
    or feeds — this only affects the market-relevance gate, so no regenerate_news_feeds()
    call is needed afterward (unlike term_expansion.apply_expansion)."""
    new_cfg = json.loads(json.dumps(cfg, ensure_ascii=False))
    market = new_cfg.setdefault("market", {})
    terms = market.setdefault("market_terms", [])
    existing_lower = {t.lower() for t in terms}
    for name in selected_names or []:
        name = (name or "").strip()
        if name and name.lower() not in existing_lower:
            terms.append(name)
            existing_lower.add(name.lower())
    return new_cfg
