"""AI-assisted city/region market-term discovery (HANDOFF §7: "Auto-suggest city/region
market terms to further reduce market-filter over-drop").

Problem this closes: the news market gate (scrapers/news.py market_signal) recognizes an
item as in-market via the country name, its demonym, or a market_term match — the wizard
already auto-populates the country name + demonym + native-script name (config.py's
run_wizard), but sub-country geography (a city or region genuinely relevant to the study's
category, e.g. the country's major consuming/manufacturing hubs for that product) has
always required the user to type it in by hand in Source plan. That's real, valuable
coverage left on the table by default — an article that only ever names "Lagos" or
"Ibadan," never "Nigeria," is exactly the kind of in-market-but-undetected item the
existing demonym fix was built to catch, just one geographic level down.

Same suggestion+validation posture as outlet_discovery.py/source_discovery.py/
term_expansion.py: Claude proposes REAL, well-known places, nothing is fabricated, and
nothing is added to market_terms until the user reviews and confirms — reusing
outlet_discovery.apply_outlets() for the actual write, since both features do the exact
same thing at that point (append confirmed strings to market.market_terms, deduped).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

CAP = 20
MAX_TOKENS = 1500


def build_prompt(cfg: Dict[str, Any]) -> str:
    market = cfg.get("market", {})
    country = market.get("country", "") or "an unspecified market"
    category = cfg.get("product", {}).get("category", "") or "this study's product category"
    existing = market.get("market_terms", [])

    rules = [
        "- Every place must be REAL — do not invent a name or guess at one you are not "
        "confident actually exists in this country.",
        "- Do not repeat the country's own name itself, or generic directions (\"the north\", "
        "\"coastal areas\") — name actual, specific, named cities/regions/states/provinces.",
    ]
    if existing:
        rules.append("- Do not repeat any of these already-configured market terms: "
                     + ", ".join(existing))
    rules.append("- No commentary outside the JSON.")

    return "\n".join([
        f"You are identifying REAL cities and regions within {country} that are genuinely "
        f"significant for the product category \"{category}\" — major population/consumption "
        f"hubs, manufacturing or distribution centers, or regions with real notable activity "
        f"for this category specifically (not just the largest cities in general, unless "
        f"those genuinely are the category's real hubs too).",
        "",
        "Return ONLY a JSON object with this key:",
        '  "terms": [ {"name": "<the real city or region name, as commonly written in '
        'English/local usage>", "why": "<one short, specific reason it matters for this '
        f'category in this market>"}} ] — up to {CAP}, most significant first',
        "",
        "Rules:",
        *rules,
    ])


def parse_terms(text: str) -> List[Dict[str, str]]:
    if not text:
        raise ValueError("Empty model response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object in model response")
    data = json.loads(text[start:end + 1])
    out: List[Dict[str, str]] = []
    seen_lower = set()
    for t in (data.get("terms") or [])[:CAP]:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not name or name.lower() in seen_lower:
            continue
        seen_lower.add(name.lower())
        out.append({"name": name, "why": str(t.get("why") or "").strip()})
    return out


def suggest_market_terms(cfg: Dict[str, Any], call_fn: Optional[Callable[[str, str], str]] = None,
                         model: Optional[str] = None) -> Dict[str, Any]:
    """Ask Claude for real, category-relevant cities/regions within this project's
    market. Returns candidates only — nothing is written to market_terms here; the
    caller applies a user-confirmed subset via outlet_discovery.apply_outlets() (same
    target field, same merge semantics — no need for a second apply function).

    Candidates already present (case-insensitively) in market_terms are dropped up
    front rather than left for the user to notice and uncheck by hand.
    """
    from settings import settings

    call = call_fn or (lambda p, m: __import__("analysis").call_claude(p, m, max_tokens=MAX_TOKENS))
    prompt = build_prompt(cfg)
    raw = call(prompt, model or settings.analysis_model)
    terms = parse_terms(raw)

    existing_lower = {t.lower() for t in cfg.get("market", {}).get("market_terms", [])}
    terms = [t for t in terms if t["name"].lower() not in existing_lower]

    return {"terms": terms, "_summary": {"total": len(terms)}}
