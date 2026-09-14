"""AI-assisted term/keyword expansion.

Problem this closes: a user searching a narrow everyday term (e.g. "coffee") gets back
only that one literal word — missing product-variant phrasings (instant coffee, cold
coffee, latte, cappuccino, americano), real brand/shop names active in this market
(Starbucks, Costa Coffee, Café Coffee Day, ...), and equivalents of all of that in every
OTHER language the study targets. Downstream search, tagging, and translation then only
ever see the one word the user typed.

Each variant/brand/translation, once confirmed, becomes its own keyword STRUCTURE — and
one Google/Bing News feed is generated per (language, structure), each with its own
independent ~100-results-per-query-per-date-chunk ceiling (see
config.regenerate_news_feeds's docstring for why this specific shape matters for volume,
not just recall). So this closes two problems at once: missed adjacent meaning, and a
real lever for how much data a study can actually collect.

Same suggestion+validation posture as source_discovery.py: Claude proposes REAL variants/
brands/translations — nothing is fabricated, and nothing is written to the project's
keyword structures or competitor list until the user reviews and confirms via
apply_expansion(). This is a convenience accelerant, not an oracle: a wrong or irrelevant
suggestion is just an unchecked box, never a silent fact.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

# Per-list cap: keeps the review panel scannable and keeps the number of new feeds a
# single expansion can create (each selected item -> its own feed) bounded.
CAP = 12
TRANSLATION_VARIANT_CAP = 5


def build_prompt(cfg: Dict[str, Any], term: str) -> str:
    market = cfg.get("market", {})
    country = market.get("country", "") or "an unspecified market"
    languages = [l for l in (market.get("languages") or []) if l] or ["en"]
    primary = languages[0]
    other_languages = languages[1:]

    lines = [
        f'A market-research study is searching for the everyday term "{term}" in '
        f"{country}. The study's configured languages are: {', '.join(languages)} "
        f"(primary: {primary}).",
        "",
        f'The single literal term "{term}" is too narrow on its own — the same underlying '
        "need is also expressed as different product variants, and as specific real "
        "brand/shop names people search for instead of the generic term. Surface both, "
        f"plus equivalents of the term and its top variants in every OTHER configured "
        "language"
        + (f" ({', '.join(other_languages)})." if other_languages
           else " — there are none; only one language is configured for this study."),
        "",
        "Return ONLY a JSON object with these keys:",
        f'  "variants": [ "<a real product-variant phrase in {primary} — e.g. for '
        '"coffee": "instant coffee", "cold coffee", "latte", "cappuccino", "americano", '
        f'"cold brew">", ... ] — up to {CAP}, most commonly searched/used first',
        f'  "brands": [ "<a REAL, well-known brand or shop name for this category that is '
        f'actually present in {country}>", ... ] — up to {CAP}; do NOT invent names, only '
        "ones you are genuinely confident operate in this market",
        '  "translations": { "<language code>": {"term": "<the base term in that '
        f'language>", "variants": ["<up to {TRANSLATION_VARIANT_CAP} of the most important '
        'variants above, in that language>"]} } — one entry per OTHER configured language '
        "listed above (omit this key entirely if there are none)",
        "",
        "Rules:",
        "- Every variant and brand must be something a real person would actually type "
        "into a search box or see in a real headline — no invented product names.",
        "- Translations should be how a native speaker actually phrases it (a natural "
        "loanword/transliteration where that's how it's really said in practice, not a "
        "stilted literal dictionary translation).",
        "- No commentary outside the JSON.",
    ]
    return "\n".join(lines)


def parse_expansion(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("Empty model response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object in model response")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        # A truncated response (hit the token budget mid-object) and a genuinely
        # malformed one look identical to json.loads -- but the former is common
        # enough here (translations scale with language count) to name explicitly
        # rather than surfacing a bare parser position to the wizard. Unbalanced
        # brace/bracket counts across the WHOLE raw text are a reliable truncation
        # signal (a genuinely malformed-but-complete response is still balanced).
        unbalanced = (text.count("{") != text.count("}")) or (text.count("[") != text.count("]"))
        hint = (" -- looks like the response was cut off before finishing (a "
               "too-small token budget for how many languages/variants were "
               "requested), not malformed JSON" if unbalanced else "")
        raise ValueError(f"Could not parse model response as JSON: {exc}{hint}") from exc

    variants = [str(v).strip() for v in (data.get("variants") or []) if v and str(v).strip()][:CAP]
    brands = [str(b).strip() for b in (data.get("brands") or []) if b and str(b).strip()][:CAP]

    translations: Dict[str, Dict[str, Any]] = {}
    for lang, entry in (data.get("translations") or {}).items():
        if not isinstance(entry, dict):
            continue
        t_term = str(entry.get("term") or "").strip()
        t_variants = [str(v).strip() for v in (entry.get("variants") or [])
                     if v and str(v).strip()][:TRANSLATION_VARIANT_CAP]
        if t_term or t_variants:
            translations[str(lang)] = {"term": t_term, "variants": t_variants}

    return {"variants": variants, "brands": brands, "translations": translations}


def suggest_terms(cfg: Dict[str, Any], term: str,
                  call_fn: Optional[Callable[[str, str], str]] = None,
                  model: Optional[str] = None) -> Dict[str, Any]:
    """Ask Claude to expand `term` into product variants, real brand/shop names, and
    per-language translations for this project's market+languages. Returns candidates
    only — nothing is written to the project config here; see apply_expansion()."""
    from settings import settings

    term = (term or "").strip()
    if not term:
        raise ValueError("A term is required (e.g. the project's category or a keyword).")

    # Real bug, found live: a fixed 1500-token budget truncates the JSON response mid-
    # object once a study has enough languages -- confirmed with a 10-language study
    # (several Indic scripts, which tokenize far less efficiently per character than
    # English) producing a literal "Expecting ',' delimiter" json.loads failure on the
    # cut-off output. Output size scales with language count (one "term" + up to
    # TRANSLATION_VARIANT_CAP variants per language), not just CAP variants/brands, so
    # the budget must scale with it too -- a bigger fixed constant would just move the
    # same failure to a study with even more languages.
    n_languages = len(cfg.get("market", {}).get("languages", []) or [])
    max_tokens = min(8000, 1500 + 350 * n_languages)
    call = call_fn or (lambda p, m: __import__("analysis").call_claude(p, m, max_tokens=max_tokens))
    prompt = build_prompt(cfg, term)
    raw = call(prompt, model or settings.analysis_model)
    result = parse_expansion(raw)
    result["term"] = term
    result["_summary"] = {
        "variants": len(result["variants"]),
        "brands": len(result["brands"]),
        "translations": len(result["translations"]),
    }
    return result


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, fallback: str = "term") -> str:
    """ASCII-only slug for use as a dict key suffix. A non-Latin-script string (Hindi,
    Telugu, Tamil, ...) — the exact case this module exists for — has NO characters that
    survive the [a-z0-9] filter, so it always collapses to the same empty string. Callers
    iterating a list MUST pass a distinct `fallback` per item (its index is enough) or
    every non-Latin-script entry in that list silently collides on the same generic key
    and overwrites the previous one (confirmed live: "इंस्टेंट कॉफी" and "कोल्ड कॉफी"
    both slugged to "term" before this fix)."""
    s = _SLUG_RE.sub("_", (text or "").strip().lower()).strip("_")
    return s or fallback


def apply_expansion(
    cfg: Dict[str, Any],
    term: str,
    *,
    variants: Optional[List[str]] = None,
    brands: Optional[List[str]] = None,
    translations: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Apply a user-CONFIRMED subset of suggest_terms()'s output into the project config.

    Each selected variant/brand/translated term becomes its OWN keyword structure under
    the relevant language — own feed, own ~100-result ceiling once
    config.regenerate_news_feeds() is called on the result (this function does not call
    it itself, so it stays a pure, easily-tested config transform; the caller is
    responsible for regenerating feeds and persisting). Brands are also added to
    cfg["competitors"] (deduped, order-preserving) so the existing brand_focus analysis
    tagging picks them up.

    Real gap found live (user report: a bare category term like "coffee" false-
    positives on unrelated content whose headline happens to contain it as a
    substring/proper-noun, e.g. a Hindi political debate show literally named
    "Coffee Par Kurukshetra") — confirmed brands/variants used to feed ONLY the News
    query structures above, never scrapers/base.py's relevance_terms(cfg), which is
    what GDELT's title re-validation and News's own headline-match/OR-filter
    actually check against. A user expanding "coffee" into espresso/cappuccino/cold
    brew/Nescafé/Starbucks previously got MORE, narrower feeds fetched but ZERO
    improvement to relevance validation itself, since the broad "coffee" term
    already in relevance_terms still matched everything regardless of what else was
    added. Every confirmed variant/brand/translated term is now ALSO merged into
    relevance_terms (deduped case-insensitively, existing terms and their order
    preserved) so genuinely specific matches become possible going forward.

    Returns a NEW config dict; does not mutate the input.
    """
    new_cfg = json.loads(json.dumps(cfg, ensure_ascii=False))  # deep copy, unicode-safe
    languages = [l for l in (new_cfg.get("market", {}).get("languages") or []) if l] or ["en"]
    primary = languages[0]
    by_language = new_cfg.setdefault("keywords", {}).setdefault("by_language", {})
    primary_slots = by_language.setdefault(primary, {})
    base_slug = _slug(term)
    confirmed_terms: List[str] = []

    # Every list below is enumerated so a non-Latin-script entry (which always slugs to
    # the same fallback) still gets a UNIQUE key via its index, instead of silently
    # colliding with and overwriting a previous entry's structure.
    for i, v in enumerate(variants or []):
        primary_slots[f"{base_slug}_variant_{_slug(v, fallback=str(i))}"] = [v]
        confirmed_terms.append(v)

    competitors = new_cfg.setdefault("competitors", [])
    existing_lower = {c.lower() for c in competitors}
    for i, b in enumerate(brands or []):
        primary_slots[f"{base_slug}_brand_{_slug(b, fallback=str(i))}"] = [b]
        confirmed_terms.append(b)
        if b.lower() not in existing_lower:
            competitors.append(b)
            existing_lower.add(b.lower())

    for lang, entry in (translations or {}).items():
        lang_slots = by_language.setdefault(lang, {})
        t_term = (entry or {}).get("term", "")
        if t_term:
            lang_slots[f"{base_slug}_translated"] = [t_term]
            confirmed_terms.append(t_term)
        for i, v in enumerate((entry or {}).get("variants", []) or []):
            lang_slots[f"{base_slug}_variant_{_slug(v, fallback=str(i))}"] = [v]
            confirmed_terms.append(v)

    relevance_terms = new_cfg.setdefault("relevance_terms", [])
    seen_lower = {t.lower() for t in relevance_terms if t}
    for t in confirmed_terms:
        if t and t.lower() not in seen_lower:
            relevance_terms.append(t)
            seen_lower.add(t.lower())

    return new_cfg
