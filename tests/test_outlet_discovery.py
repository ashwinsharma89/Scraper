"""AI outlet discovery: parse + apply (LLM mocked)."""
import json

import config
import outlet_discovery


def _cfg():
    return config.run_wizard({
        "market": {"country": "India", "languages": ["en", "hi"]},
        "product": {"brand": "", "category": "coffee", "category_type": "fmcg_food"},
    })


LLM_JSON = json.dumps({
    "outlets": [
        {"name": "Scroll.in", "domain": "scroll.in", "category": "news", "language": "en",
         "why": "major independent English news site"},
        {"name": "ScoopWhoop", "domain": "scoopwhoop.com", "category": "culture", "language": "en",
         "why": "large youth/culture blog"},
        {"name": "NDTV", "domain": "ndtv.com", "category": "news", "language": "en",
         "why": "major broadcaster"},
        {"name": "Digit", "domain": "digit.in", "category": "tech", "language": "en",
         "why": "well-known tech publication"},
        {"name": "दैनिक भास्कर", "domain": "bhaskar.com", "category": "news", "language": "hi",
         "why": "top Hindi-language daily"},
    ],
})


def test_parse_outlets_caps_dedupes_and_flags_caution():
    r = outlet_discovery.parse_outlets("noise " + LLM_JSON + " trailing")
    names = [o["name"] for o in r["outlets"]]
    assert names == ["Scroll.in", "ScoopWhoop", "NDTV", "Digit", "दैनिक भास्कर"]
    by_name = {o["name"]: o for o in r["outlets"]}
    # Short single-word names flagged for a second look; multi-word/longer ones are not.
    assert by_name["Digit"]["caution"] is True
    assert by_name["NDTV"]["caution"] is True  # 4-char single word -> caution
    assert by_name["Scroll.in"]["caution"] is False  # >6 chars
    assert by_name["ScoopWhoop"]["caution"] is False
    assert by_name["दैनिक भास्कर"]["caution"] is False  # multi-word


def test_parse_outlets_dedupes_case_insensitively():
    raw = json.dumps({"outlets": [
        {"name": "NDTV", "domain": "ndtv.com"},
        {"name": "ndtv", "domain": "ndtv.com"},
    ]})
    r = outlet_discovery.parse_outlets(raw)
    assert len(r["outlets"]) == 1


def test_parse_outlets_salvages_complete_objects_from_a_truncated_response():
    """Real bug found live: an earlier CAP/max_tokens combination truncated the model's
    response mid-object (cut off inside a "domain" field). The old parser raised and threw
    away every outlet, including the ones already fully generated before the cutoff. This
    must salvage the complete ones instead."""
    truncated = """{"outlets": [
        {"name": "Scroll.in", "domain": "scroll.in", "category": "news", "language": "en", "why": "x"},
        {"name": "NDTV", "domain": "ndtv.com", "category": "news", "language": "en", "why": "y"},
        {"name": "Vijaya Karnataka", "domain":"""
    r = outlet_discovery.parse_outlets(truncated)
    names = [o["name"] for o in r["outlets"]]
    assert names == ["Scroll.in", "NDTV"]  # the two complete ones survive
    assert "Vijaya Karnataka" not in names  # the incomplete trailing one is dropped, not crashed on


def test_parse_outlets_raises_only_when_nothing_can_be_salvaged():
    try:
        outlet_discovery.parse_outlets('{"outlets": [{"name": "X", "domain":')
        assert False, "should have raised — nothing complete to salvage"
    except ValueError:
        pass


def test_parse_outlets_empty_response_raises():
    try:
        outlet_discovery.parse_outlets("")
        assert False, "should have raised"
    except ValueError:
        pass


def test_suggest_outlets_calls_llm_and_summarizes():
    calls = []

    def fake_call(prompt, model):
        calls.append(prompt)
        return LLM_JSON

    r = outlet_discovery.suggest_outlets(_cfg(), call_fn=fake_call)
    assert r["_summary"]["total"] == 5
    assert r["_summary"]["caution"] == 2  # NDTV, Digit
    assert "India" in calls[0]
    assert "hi" in calls[0]  # non-English configured language named in the prompt


def test_prompt_asks_for_broad_categories_not_just_news():
    p = outlet_discovery.build_prompt(_cfg())
    for word in ("business", "tech", "sports", "lifestyle", "culture", "regional"):
        assert word in p.lower()
    assert "NOT limited to hard news" in p or "not limited to hard news" in p.lower()


def test_apply_outlets_adds_to_market_terms_deduped():
    cfg = _cfg()
    cfg["market"]["market_terms"] = ["India", "Indian"]
    new_cfg = outlet_discovery.apply_outlets(cfg, ["Scroll.in", "NDTV", "india"])  # "india" dup, case-diff
    terms = new_cfg["market"]["market_terms"]
    assert terms == ["India", "Indian", "Scroll.in", "NDTV"]


def test_apply_outlets_does_not_mutate_input():
    cfg = _cfg()
    original = json.loads(json.dumps(cfg))
    outlet_discovery.apply_outlets(cfg, ["Scroll.in"])
    assert cfg == original


def test_apply_outlets_then_market_signal_recognizes_the_outlet():
    """End-to-end: a confirmed outlet name becomes real market evidence via the
    word-boundary-safe market_signal() fix, without needing the country's name in the
    article at all."""
    from scrapers import news

    cfg = _cfg()
    new_cfg = outlet_discovery.apply_outlets(cfg, ["Scroll.in"])
    terms = new_cfg["market"]["market_terms"]
    assert news.market_signal("A piece about coffee culture in cafes", "scroll.in", terms, ".in") is True
    # An unrelated outlet with no market signal is still correctly dropped.
    assert news.market_signal("A piece about coffee culture", "randomblog.com", terms, ".in") is False


def test_apply_outlets_caution_flagged_name_does_not_false_positive_after_boundary_fix():
    """The two safety nets working together: even a caution-flagged short name (Digit) is
    safe to add now, because market_signal's word-boundary fix (scrapers/news.py) prevents
    it from matching inside unrelated words like "digital" — the caution flag is about
    prompting a human's review, not a claim that the name is unsafe to ever use."""
    from scrapers import news

    cfg = _cfg()
    new_cfg = outlet_discovery.apply_outlets(cfg, ["Digit"])
    terms = new_cfg["market"]["market_terms"]
    assert news.market_signal("coffee house antidote to lonely digital lives", "ft.com", terms, "") is False
    assert news.market_signal("Digit reviews the latest coffee gadgets", "digit.in", terms, "") is True
