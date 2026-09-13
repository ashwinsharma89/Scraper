"""AI category classification: parse + confidence gating (LLM mocked)."""
import json

import category_discovery


LLM_JSON = json.dumps({
    "category": "coffee / food & beverage lifestyle",
    "confidence": 0.93,
    "reasoning": "Coffee is a consumer food & beverage / lifestyle product.",
    "structured_data_hint": None,
})

LLM_AMBIGUOUS_JSON = json.dumps({
    "category": "apple / consumer electronics OR produce",
    "confidence": 0.4,
    "reasoning": "\"Apple\" could mean the fruit or the technology brand.",
    "structured_data_hint": None,
})

LLM_STRUCTURED_JSON = json.dumps({
    "category": "healthcare / medical practitioners",
    "confidence": 0.88,
    "reasoning": "Doctors implies a healthcare practitioner directory vertical.",
    "structured_data_hint": "practitioner_directory: name, credentials, specialty",
})


def test_parse_classification_confident_case():
    r = category_discovery.parse_classification(LLM_JSON)
    assert r["category"] == "coffee / food & beverage lifestyle"
    assert r["confidence"] == 0.93
    assert r["needs_confirmation"] is False
    assert r["structured_data_hint"] is None


def test_parse_classification_low_confidence_flags_needs_confirmation():
    r = category_discovery.parse_classification(LLM_AMBIGUOUS_JSON)
    assert r["confidence"] == 0.4
    assert r["needs_confirmation"] is True


def test_parse_classification_captures_structured_data_hint():
    r = category_discovery.parse_classification(LLM_STRUCTURED_JSON)
    assert r["structured_data_hint"] == "practitioner_directory: name, credentials, specialty"


def test_parse_classification_clamps_out_of_range_confidence():
    raw = json.dumps({"category": "x", "confidence": 1.7})
    assert category_discovery.parse_classification(raw)["confidence"] == 1.0
    raw = json.dumps({"category": "x", "confidence": -0.3})
    assert category_discovery.parse_classification(raw)["confidence"] == 0.0


def test_parse_classification_missing_category_raises():
    try:
        category_discovery.parse_classification(json.dumps({"confidence": 0.9}))
        assert False, "should have raised"
    except ValueError:
        pass


def test_parse_classification_empty_response_raises():
    try:
        category_discovery.parse_classification("")
        assert False, "should have raised"
    except ValueError:
        pass


def test_classify_category_calls_llm_with_term_and_geo_scope():
    calls = []

    def fake_call(prompt, model):
        calls.append(prompt)
        return LLM_JSON

    r = category_discovery.classify_category(
        "coffee", geo_scope={"level": "city", "value": "Bangalore", "country": "India"},
        call_fn=fake_call,
    )
    assert r["category"] == "coffee / food & beverage lifestyle"
    assert "coffee" in calls[0] and "Bangalore" in calls[0] and "India" in calls[0]


def test_classify_category_requires_a_term():
    try:
        category_discovery.classify_category("", call_fn=lambda p, m: LLM_JSON)
        assert False, "should have raised"
    except ValueError:
        pass


def test_classify_category_works_without_geo_scope():
    r = category_discovery.classify_category("coffee", call_fn=lambda p, m: LLM_JSON)
    assert r["category"] == "coffee / food & beverage lifestyle"
