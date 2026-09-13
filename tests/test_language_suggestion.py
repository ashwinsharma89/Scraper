"""AI-suggested, human-confirmed languages (DESIGN_01 §12 wizard step c)."""
import json

import language_suggestion as ls

LLM_JSON = json.dumps({
    "languages": [
        {"code": "en", "name": "English", "why": "widely used for coffee-culture content"},
        {"code": "hi", "name": "Hindi", "why": "dominant language in the market"},
        {"code": "kn", "name": "Kannada", "why": "regional coverage in Bangalore"},
    ],
})


def test_suggest_languages_returns_candidates_flagged_known():
    r = ls.suggest_languages("coffee", geo_scope={"level": "country", "value": "India",
                                                   "country": "India"},
                             call_fn=lambda p, m: LLM_JSON)
    codes = {l["code"] for l in r["languages"]}
    assert codes == {"en", "hi", "kn"}
    assert all(l["known"] for l in r["languages"])
    assert r["_summary"]["total"] == 3
    assert r["_summary"]["unknown_codes"] == 0


def test_suggest_languages_flags_a_code_not_in_the_reference_table_rather_than_dropping_it():
    raw = json.dumps({"languages": [{"code": "zz", "name": "Madeupian", "why": "test"}]})
    r = ls.suggest_languages("coffee", call_fn=lambda p, m: raw)
    assert len(r["languages"]) == 1
    assert r["languages"][0]["known"] is False
    assert r["_summary"]["unknown_codes"] == 1


def test_suggest_languages_requires_a_category():
    try:
        ls.suggest_languages("", call_fn=lambda p, m: LLM_JSON)
        assert False, "should have raised"
    except ValueError:
        pass


def test_parse_languages_dedupes_by_code():
    raw = json.dumps({"languages": [{"code": "en", "name": "English"},
                                    {"code": "EN", "name": "English dup"}]})
    langs = ls.parse_languages(raw)
    assert len(langs) == 1


def test_parse_languages_empty_response_raises():
    try:
        ls.parse_languages("")
        assert False, "should have raised"
    except ValueError:
        pass


def test_build_prompt_includes_geo_scope_value():
    prompt = ls.build_prompt("coffee", {"level": "city", "value": "Bangalore", "country": "India"})
    assert "Bangalore" in prompt
    assert "coffee" in prompt
