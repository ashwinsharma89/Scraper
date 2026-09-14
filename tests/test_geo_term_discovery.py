"""AI city/region market-term discovery: parse + suggest (LLM mocked). Applying a
confirmed selection reuses outlet_discovery.apply_outlets() — see test_outlet_discovery.py
for coverage of the shared apply/market_signal path."""
import json

import config
import geo_term_discovery as gtd


def _cfg(market_terms=None):
    cfg = config.run_wizard({
        "market": {"country": "Nigeria", "languages": ["en"]},
        "product": {"brand": "", "category": "instant noodles", "category_type": "fmcg_food"},
    })
    if market_terms is not None:
        cfg["market"]["market_terms"] = market_terms
    return cfg


LLM_JSON = json.dumps({
    "terms": [
        {"name": "Lagos", "why": "largest consumer market and distribution hub"},
        {"name": "Kano", "why": "major northern population and trade center"},
        {"name": "Ibadan", "why": "large southwestern city with significant FMCG demand"},
    ],
})


def test_parse_terms_caps_and_dedupes_case_insensitively():
    raw = json.dumps({"terms": [
        {"name": "Lagos", "why": "x"},
        {"name": "lagos", "why": "dup"},
        {"name": "Kano", "why": "y"},
    ]})
    terms = gtd.parse_terms(raw)
    assert [t["name"] for t in terms] == ["Lagos", "Kano"]


def test_parse_terms_empty_response_raises():
    try:
        gtd.parse_terms("")
        assert False, "should have raised"
    except ValueError:
        pass


def test_parse_terms_no_json_object_raises():
    try:
        gtd.parse_terms("not json at all")
        assert False, "should have raised"
    except ValueError:
        pass


def test_build_prompt_names_the_real_country_and_category():
    p = gtd.build_prompt(_cfg())
    assert "Nigeria" in p
    assert "instant noodles" in p


def test_build_prompt_tells_the_model_not_to_repeat_existing_market_terms():
    cfg = _cfg(market_terms=["Nigeria", "Nigerian", "Abuja"])
    p = gtd.build_prompt(cfg)
    assert "Abuja" in p  # named explicitly so the model doesn't re-suggest it


def test_suggest_market_terms_calls_llm_and_summarizes():
    calls = []

    def fake_call(prompt, model):
        calls.append(prompt)
        return LLM_JSON

    r = gtd.suggest_market_terms(_cfg(), call_fn=fake_call)
    assert r["_summary"]["total"] == 3
    names = [t["name"] for t in r["terms"]]
    assert names == ["Lagos", "Kano", "Ibadan"]
    assert "Nigeria" in calls[0]


def test_suggest_market_terms_drops_candidates_already_configured():
    """A candidate the wizard (or a prior suggestion round) already added to
    market_terms shouldn't be re-suggested for the user to notice and uncheck."""
    cfg = _cfg(market_terms=["Nigeria", "Nigerian", "Lagos"])
    r = gtd.suggest_market_terms(cfg, call_fn=lambda p, m: LLM_JSON)
    names = [t["name"] for t in r["terms"]]
    assert "Lagos" not in names
    assert names == ["Kano", "Ibadan"]
    assert r["_summary"]["total"] == 2


def test_suggested_terms_apply_via_the_shared_outlet_apply_path():
    """Confirmed end-to-end: geo_term_discovery only ever suggests; applying a
    confirmed selection reuses outlet_discovery.apply_outlets() unchanged, since both
    features append plain strings to the same market.market_terms field."""
    import outlet_discovery

    cfg = _cfg(market_terms=["Nigeria", "Nigerian"])
    suggestion = gtd.suggest_market_terms(cfg, call_fn=lambda p, m: LLM_JSON)
    selected = [t["name"] for t in suggestion["terms"]]

    new_cfg = outlet_discovery.apply_outlets(cfg, selected)
    assert new_cfg["market"]["market_terms"] == ["Nigeria", "Nigerian", "Lagos", "Kano", "Ibadan"]
