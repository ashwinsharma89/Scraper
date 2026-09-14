"""AI term expansion: parse + apply (LLM mocked)."""
import json

import config
import term_expansion


def _cfg():
    return config.run_wizard({
        "market": {"country": "India", "languages": ["en", "hi", "te"]},
        "product": {"brand": "", "category": "coffee", "category_type": "fmcg_food"},
    })


LLM_JSON = json.dumps({
    "variants": ["instant coffee", "cold coffee", "latte", "cappuccino", "americano"],
    "brands": ["Starbucks", "Costa Coffee", "Café Coffee Day"],
    "translations": {
        "hi": {"term": "कॉफी", "variants": ["इंस्टेंट कॉफी", "कोल्ड कॉफी"]},
        "te": {"term": "కాఫీ", "variants": ["ఇన్‌స్టంట్ కాఫీ"]},
    },
})


def test_parse_expansion_caps_and_keys():
    r = term_expansion.parse_expansion("noise " + LLM_JSON + " trailing")
    assert r["variants"] == ["instant coffee", "cold coffee", "latte", "cappuccino", "americano"]
    assert r["brands"] == ["Starbucks", "Costa Coffee", "Café Coffee Day"]
    assert r["translations"]["hi"]["term"] == "कॉफी"
    assert r["translations"]["hi"]["variants"] == ["इंस्टेंट कॉफी", "कोल्ड कॉफी"]
    assert r["translations"]["te"]["term"] == "కాఫీ"


def test_parse_expansion_empty_response_raises():
    try:
        term_expansion.parse_expansion("")
        assert False, "should have raised"
    except ValueError:
        pass


def test_parse_expansion_drops_malformed_translation_entries():
    raw = json.dumps({"variants": [], "brands": [],
                       "translations": {"hi": "not a dict", "te": {"term": "", "variants": []}}})
    r = term_expansion.parse_expansion(raw)
    assert r["translations"] == {}  # both malformed/empty entries dropped


def test_parse_expansion_caps_variants_and_brands_at_CAP():
    many = [f"variant {i}" for i in range(term_expansion.CAP + 5)]
    raw = json.dumps({"variants": many, "brands": many, "translations": {}})
    r = term_expansion.parse_expansion(raw)
    assert len(r["variants"]) == term_expansion.CAP
    assert len(r["brands"]) == term_expansion.CAP


def test_suggest_terms_calls_llm_and_summarizes():
    calls = []

    def fake_call(prompt, model):
        calls.append(prompt)
        return LLM_JSON

    r = term_expansion.suggest_terms(_cfg(), "coffee", call_fn=fake_call)
    assert r["term"] == "coffee"
    assert r["_summary"] == {"variants": 5, "brands": 3, "translations": 2}
    assert "coffee" in calls[0] and "India" in calls[0]
    assert "hi" in calls[0] and "te" in calls[0]  # other configured languages named in prompt


def test_suggest_terms_scales_max_tokens_with_language_count(monkeypatch):
    """Real bug, found live: a fixed 1500-token budget truncated the JSON response
    mid-object for a real 10-language study (several Indic scripts, which tokenize
    far less efficiently per character than English), producing a literal
    "Expecting ',' delimiter" json.loads failure. The budget must scale with
    language count, since that's what actually drives output size."""
    import analysis

    captured = {}

    def fake_call_claude(prompt, model=None, max_tokens=3000):
        captured["max_tokens"] = max_tokens
        return LLM_JSON

    monkeypatch.setattr(analysis, "call_claude", fake_call_claude)

    cfg_few = config.run_wizard({"market": {"country": "India", "languages": ["en"]},
                                 "product": {"brand": "", "category": "coffee",
                                            "category_type": "fmcg_food"}})
    term_expansion.suggest_terms(cfg_few, "coffee")
    few_langs_tokens = captured["max_tokens"]

    cfg_many = config.run_wizard({
        "market": {"country": "India",
                  "languages": ["en", "hi", "ta", "te", "kn", "ml", "mr", "gu", "pa", "bn"]},
        "product": {"brand": "", "category": "coffee", "category_type": "fmcg_food"},
    })
    term_expansion.suggest_terms(cfg_many, "coffee")
    many_langs_tokens = captured["max_tokens"]

    assert many_langs_tokens > few_langs_tokens
    assert many_langs_tokens >= 1500 + 350 * 10 - 1  # the 10-language case gets real headroom


def test_parse_expansion_truncated_json_gets_an_actionable_error():
    """The exact real error shape reported live: 'Expecting , delimiter' from a
    response cut off mid-object (one completed translation entry, one cut short)."""
    truncated = ('{"variants": ["instant coffee"], "brands": ["Starbucks"], '
                '"translations": {"hi": {"term": "x", "variants": ["y"]}, "te": {"term')
    try:
        term_expansion.parse_expansion(truncated)
        assert False, "should have raised"
    except ValueError as e:
        assert "cut off" in str(e)


def test_suggest_terms_requires_a_term():
    try:
        term_expansion.suggest_terms(_cfg(), "", call_fn=lambda p, m: LLM_JSON)
        assert False, "should have raised"
    except ValueError:
        pass


def test_prompt_names_market_and_other_languages_not_primary():
    p = term_expansion.build_prompt(_cfg(), "coffee")
    assert "coffee" in p and "India" in p
    assert "hi, te" in p or ("hi" in p and "te" in p)
    # Primary language itself shouldn't be listed as one of the "OTHER" translation targets.
    assert "(hi, te)" in p or "hi, te" in p


def test_apply_expansion_creates_one_structure_per_selection():
    cfg = _cfg()
    new_cfg = term_expansion.apply_expansion(
        cfg, "coffee",
        variants=["instant coffee", "cold coffee"],
        brands=["Starbucks"],
        translations={"hi": {"term": "कॉफी", "variants": ["इंस्टेंट कॉफी"]}},
    )
    en_slots = new_cfg["keywords"]["by_language"]["en"]
    assert en_slots["coffee_variant_instant_coffee"] == ["instant coffee"]
    assert en_slots["coffee_variant_cold_coffee"] == ["cold coffee"]
    assert en_slots["coffee_brand_starbucks"] == ["Starbucks"]
    hi_slots = new_cfg["keywords"]["by_language"]["hi"]
    assert hi_slots["coffee_translated"] == ["कॉफी"]
    # Non-Latin-script variants have no [a-z0-9] to slug, so the key falls back to the
    # item's index (0 here, the only translated variant) — must still be present and
    # correct, not silently collapsed onto a shared generic key.
    assert hi_slots["coffee_variant_0"] == ["इंस्टेंट कॉफी"]
    # Brand also added to competitors so brand_focus analysis picks it up.
    assert "Starbucks" in new_cfg["competitors"]


def test_apply_expansion_merges_confirmed_terms_into_relevance_terms():
    """Real gap found live (user report): a bare category term like "coffee" alone in
    relevance_terms false-positives on unrelated content whose headline happens to
    contain it as a substring/proper noun (e.g. a real Hindi political debate show
    literally titled "Coffee Par Kurukshetra"). Confirmed variants/brands/
    translations previously fed ONLY the News query structures, never
    relevance_terms itself -- which is what GDELT's title re-validation and News's
    own headline-match/OR-filter actually check. Without this, expanding a term
    fetched MORE feeds but did nothing to make matching itself more precise."""
    cfg = _cfg()
    before = set(cfg.get("relevance_terms", []))

    new_cfg = term_expansion.apply_expansion(
        cfg, "coffee",
        variants=["instant coffee", "cold coffee"],
        brands=["Starbucks"],
        translations={"hi": {"term": "कॉफी", "variants": ["इंस्टेंट कॉफी"]}},
    )
    terms = new_cfg["relevance_terms"]
    # Every existing term survives untouched...
    assert before <= set(terms)
    # ...and every confirmed selection is now also a relevance term.
    for t in ["instant coffee", "cold coffee", "Starbucks", "कॉफी", "इंस्टेंट कॉफी"]:
        assert t in terms


def test_apply_expansion_relevance_terms_merge_dedupes_case_insensitively():
    cfg = _cfg()
    cfg["relevance_terms"] = ["Starbucks"]
    new_cfg = term_expansion.apply_expansion(cfg, "coffee", brands=["starbucks"])
    assert new_cfg["relevance_terms"].count("Starbucks") == 1
    assert "starbucks" not in new_cfg["relevance_terms"]  # the existing casing wins


def test_apply_expansion_native_script_variants_dont_collide():
    """The bug this guards against: multiple non-Latin-script variants in the SAME
    language must each get a distinct structure — before the index-fallback fix, both of
    these silently slugged to the same "term" key and the second overwrote the first."""
    cfg = _cfg()
    new_cfg = term_expansion.apply_expansion(
        cfg, "coffee",
        translations={"hi": {"term": "", "variants": ["इंस्टेंट कॉफी", "कोल्ड कॉफी"]}},
    )
    hi_slots = new_cfg["keywords"]["by_language"]["hi"]
    variant_keys = [k for k in hi_slots if k.startswith("coffee_variant_")]
    assert len(variant_keys) == 2
    values = sorted(v[0] for v in hi_slots.values() if v)
    assert values == ["इंस्टेंट कॉफी", "कोल्ड कॉफी"]


def test_apply_expansion_dedupes_competitors_case_insensitively():
    cfg = _cfg()
    cfg["competitors"] = ["starbucks"]  # already present, different case
    new_cfg = term_expansion.apply_expansion(cfg, "coffee", brands=["Starbucks", "Costa Coffee"])
    assert new_cfg["competitors"].count("Starbucks") == 0  # not re-added under new casing
    assert new_cfg["competitors"] == ["starbucks", "Costa Coffee"]


def test_apply_expansion_does_not_mutate_input():
    cfg = _cfg()
    original = json.loads(json.dumps(cfg))
    term_expansion.apply_expansion(cfg, "coffee", variants=["latte"], brands=["Starbucks"])
    assert cfg == original


def test_apply_expansion_then_regenerate_feeds_produces_one_feed_per_selection():
    """End-to-end: each selected variant/brand/translation becomes its own feed once
    regenerate_news_feeds runs on the applied config — this is the actual volume lever."""
    cfg = _cfg()
    before = len(cfg["source_plan"]["google_news_feeds"])  # just "coffee" (category_generic)
    new_cfg = term_expansion.apply_expansion(
        cfg, "coffee",
        variants=["instant coffee", "cold coffee", "latte"],
        brands=["Starbucks", "Costa Coffee"],
        translations={"hi": {"term": "कॉफी", "variants": []},
                      "te": {"term": "కాఫీ", "variants": []}},
    )
    regenerated = config.regenerate_news_feeds(new_cfg)
    after = len(regenerated["source_plan"]["google_news_feeds"])
    # before: 1 (en category_generic). New structures: 3 variants + 2 brands (en) +
    # 1 translated term each for hi and te = 7 new -> 8 total.
    assert before == 1
    assert after == 8


def test_apply_expansion_relevance_terms_merge_improves_gdelt_title_matching():
    """Concrete proof of the real, practical value: a real GDELT-style headline that
    mentions a confirmed brand but never says the bare category word "coffee" at all
    was previously invisible to GDELT's own title re-validation (which checks
    relevance_terms) -- confirming a brand via Expand-a-term now makes it catch this
    genuine, on-topic story that keyword-only matching on "coffee" alone would miss."""
    from scrapers import gdelt

    cfg = _cfg()
    cfg["source_plan"]["gdelt"] = {"sourcecountry": "IN"}
    payload = ('{"articles":[{"title":"Nescafe launches new instant range",'
               '"url":"http://a","seendate":"20260115T120000Z","domain":"news.in"}]}')

    class R:
        status_code = 200
        text = payload

    before_terms = list(cfg.get("relevance_terms", []))
    res_before = gdelt.collect(cfg, {"start_date": "2026-01-01", "end_date": "2026-01-31"},
                               fetch_fn=lambda u: R())
    assert res_before.items == []  # "Nescafe" alone doesn't match bare "coffee"

    new_cfg = term_expansion.apply_expansion(cfg, "coffee", brands=["Nescafe"])
    assert "Nescafe" in new_cfg["relevance_terms"] and "Nescafe" not in before_terms
    res_after = gdelt.collect(new_cfg, {"start_date": "2026-01-01", "end_date": "2026-01-31"},
                              fetch_fn=lambda u: R())
    assert len(res_after.items) == 1
