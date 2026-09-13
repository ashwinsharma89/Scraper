"""AI-driven category classification (DESIGN_01_category-discovery.md §1).

A search term implies an unstated vertical — "coffee" implies lifestyle/food-and-beverage
sources; "doctors" implies healthcare. Today's only category concept,
`config.CATEGORY_TYPES`, is a small, hardcoded, closed enum (`config.py` line 71:
`["fmcg_food", "consumer_electronics", "fashion", "services", "b2b_industrial", "other"]`) —
exactly the kind of central list a genuinely new vertical would otherwise need a code change
to join.

This module classifies with an LLM instead, returning free text, not a value from a fixed
set — the same reasoning `term_expansion.py` already applies to keyword expansion: an
enumerated list only ever covers what someone thought to add in advance, an LLM call
generalizes to concepts nobody explicitly enumerated. `CATEGORY_TYPES` is not removed or
touched by this module — it still drives the existing, narrower `segment_applicability()`
logic, which is out of scope here.

Same honesty posture as every other AI-assisted module in this codebase: the model's own
self-reported confidence is surfaced, not hidden, so a genuinely uncertain classification can
be shown to a human for a one-glance confirmation instead of silently proceeding on a guess.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

# Below this, the wizard shows the classification for a quick human confirmation instead of
# proceeding silently — see DESIGN_01 §1's "not a universal manual gate" distinction.
LOW_CONFIDENCE_THRESHOLD = 0.6


def build_prompt(term: str, geo_scope: Optional[Dict[str, Any]] = None) -> str:
    term = (term or "").strip()
    geo_scope = geo_scope or {}
    level = geo_scope.get("level", "")
    value = geo_scope.get("value", "")
    country = geo_scope.get("country", "")
    where = f"{value} ({level}, {country})" if value and level else (country or "an unspecified market")

    return "\n".join([
        f'Classify the real-world category/vertical implied by the search term "{term}" for a '
        f"market-research study scoped to {where}.",
        "",
        "Return ONLY a JSON object with these keys:",
        '  "category": "<a short, specific, free-text label for the vertical this term '
        'belongs to — e.g. \\"coffee / food & beverage lifestyle\\" for \\"coffee\\", '
        '\\"healthcare / medical practitioners\\" for \\"doctors\\". Do NOT pick from a fixed '
        'list — describe the actual vertical.>',
        '  "confidence": <a number from 0.0 to 1.0 — your own honest confidence that this '
        "classification is correct and unambiguous for this term>",
        '  "reasoning": "<one short sentence explaining the classification>",',
        '  "structured_data_hint": "<if this category typically involves structured entity '
        'data beyond article text — e.g. practitioner name/credentials/specialty for '
        "healthcare, or null if this is ordinary editorial/article content like most consumer "
        'products and topics>"',
        "",
        "Rules:",
        "- If the term is genuinely ambiguous across multiple plausible verticals, say so in "
        "\"reasoning\" and reflect that honestly in a lower \"confidence\" — do not guess "
        "confidently at an arbitrary single interpretation.",
        "- No commentary outside the JSON.",
    ])


def parse_classification(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("Empty model response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object in model response")
    data = json.loads(text[start:end + 1])

    category = str(data.get("category") or "").strip()
    if not category:
        raise ValueError("Model response had no category")
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))  # clamp — never trust the model's range blindly

    hint = data.get("structured_data_hint")
    hint = str(hint).strip() if hint and str(hint).lower() != "null" else None

    return {
        "category": category,
        "confidence": confidence,
        "reasoning": str(data.get("reasoning") or "").strip(),
        "structured_data_hint": hint,
        "needs_confirmation": confidence < LOW_CONFIDENCE_THRESHOLD,
    }


def classify_category(term: str, geo_scope: Optional[Dict[str, Any]] = None,
                      call_fn: Optional[Callable[[str, str], str]] = None,
                      model: Optional[str] = None) -> Dict[str, Any]:
    """Classify `term` into a free-text category/vertical. Never fabricates a category for an
    empty term — raises instead, matching every other suggestion module's contract."""
    from settings import settings

    term = (term or "").strip()
    if not term:
        raise ValueError("A term is required to classify a category.")

    call = call_fn or (lambda p, m: __import__("analysis").call_claude(p, m, max_tokens=500))
    prompt = build_prompt(term, geo_scope)
    raw = call(prompt, model or settings.analysis_model)
    return parse_classification(raw)
