"""AI-suggested, human-confirmed languages for a category+geo-scope
(DESIGN_01_category-discovery.md §12 wizard step c: "AI-suggested-but-confirmed
languages" from the Decided Configuration table — blocks on explicit confirmation,
unlike most other suggestion steps, because a wrong language list silently produces
zero recall for real content rather than an obviously-wrong result to notice).

Same suggestion-then-confirm shape as every other AI-assisted module in this
codebase (source_discovery.py, term_expansion.py, outlet_discovery.py,
category_discovery.py, site_intelligence.py): the LLM proposes, config.list_languages()
(the existing reference table) validates the codes are real, and nothing is written
anywhere by this module — it only returns candidates for the wizard to show.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

CAP = 10


def build_prompt(category: str, geo_scope: Optional[Dict[str, Any]] = None) -> str:
    geo_scope = geo_scope or {}
    level = geo_scope.get("level", "")
    value = geo_scope.get("value", "")
    country = geo_scope.get("country", "")
    where = f"{value} ({level}, {country})" if value and level else (country or "an unspecified market")

    return "\n".join([
        f'For a market-research study of the category "{category}" in {where}, name the '
        f"REAL languages a person would need to cover to see genuine local coverage/discussion "
        f"— not just the country's single official language if more are actually in wide use "
        f"for this kind of content (e.g. regional-language news/blogs).",
        "",
        "Return ONLY a JSON object with this key:",
        '  "languages": [ {"code": "<real ISO 639-1 two-letter code, e.g. \\"hi\\">", '
        '"name": "<language name>", "why": "<one short reason this language matters here>"} ] '
        f"— up to {CAP}, most important first",
        "",
        "Rules:",
        "- Use REAL ISO 639-1 codes only — do not invent one.",
        "- Always include the country's dominant/official language(s) first if applicable.",
        "- No commentary outside the JSON.",
    ])


def parse_languages(text: str) -> List[Dict[str, str]]:
    if not text:
        raise ValueError("Empty model response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object in model response")
    data = json.loads(text[start:end + 1])
    out: List[Dict[str, str]] = []
    seen = set()
    for lang in (data.get("languages") or [])[:CAP]:
        code = (lang.get("code") or "").strip().lower()
        if code and code not in seen:
            seen.add(code)
            out.append({"code": code, "name": lang.get("name", ""), "why": lang.get("why", "")})
    return out


def suggest_languages(category: str, geo_scope: Optional[Dict[str, Any]] = None,
                      call_fn: Optional[Callable[[str, str], str]] = None,
                      model: Optional[str] = None) -> Dict[str, Any]:
    """Returns {"languages": [...], "_summary": {"total", "known_codes", "unknown_codes"}}.
    A suggested code not found in config.list_languages()'s reference table is still
    returned (flagged unknown=True) rather than silently dropped — an LLM naming a real
    language this tool's reference table happens to be missing is evidence worth
    surfacing to the human confirming this step, not evidence to hide.
    """
    import config as config_mod
    from settings import settings

    category = (category or "").strip()
    if not category:
        raise ValueError("category is required")

    call = call_fn or (lambda p, m: __import__("analysis").call_claude(p, m, max_tokens=1000))
    prompt = build_prompt(category, geo_scope)
    raw = call(prompt, model or settings.analysis_model)
    languages = parse_languages(raw)

    known_codes = {row["code"] for row in config_mod.list_languages()}
    known_names = {row["code"]: row["name"] for row in config_mod.list_languages()}
    for lang in languages:
        lang["known"] = lang["code"] in known_codes
        if lang["known"] and not lang.get("name"):
            lang["name"] = known_names.get(lang["code"], "")

    return {
        "category": category,
        "languages": languages,
        "_summary": {
            "total": len(languages),
            "known_codes": sum(1 for l in languages if l["known"]),
            "unknown_codes": sum(1 for l in languages if not l["known"]),
        },
    }
