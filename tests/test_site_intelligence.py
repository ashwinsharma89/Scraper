"""AI site discovery + the cross-project learning ledger (LLM mocked, storage real+isolated)."""
import json

import site_intelligence as si
import storage


LLM_JSON = json.dumps({
    "sites": [
        {"name": "ScoopWhoop", "domain": "scoopwhoop.com", "source_type": "lifestyle",
         "why": "large youth/culture blog covering food & drink"},
        {"name": "NDTV Food", "domain": "food.ndtv.com", "source_type": "news",
         "why": "major broadcaster's food vertical"},
    ],
})


def test_parse_sites_dedupes_by_domain_case_insensitive():
    raw = json.dumps({"sites": [
        {"name": "A", "domain": "Example.com"},
        {"name": "A dup", "domain": "example.com"},
    ]})
    sites = si.parse_sites(raw)
    assert len(sites) == 1
    assert sites[0]["domain"] == "example.com"


def test_parse_sites_strips_scheme_and_www():
    raw = json.dumps({"sites": [{"name": "A", "domain": "https://www.example.com/"}]})
    assert si.parse_sites(raw)[0]["domain"] == "example.com"


def test_parse_sites_empty_response_raises():
    try:
        si.parse_sites("")
        assert False, "should have raised"
    except ValueError:
        pass


def test_discover_sites_with_empty_ledger_returns_only_fresh_llm_candidates(fresh_db):
    r = si.discover_sites("coffee", call_fn=lambda p, m: LLM_JSON)
    assert r["_summary"]["total"] == 2
    assert r["_summary"]["known"] == 0
    assert r["_summary"]["needs_validation"] == 2  # nothing in the ledger yet -> all unverified
    assert {s["domain"] for s in r["sites"]} == {"scoopwhoop.com", "food.ndtv.com"}


def test_discover_sites_surfaces_ledger_known_sites_alongside_fresh_ones(fresh_db):
    # Simulate real prior history: scoopwhoop.com has a strong track record for "coffee".
    storage.record_site_outcome("scoopwhoop.com", "coffee", kept=9, dropped=1)
    storage.record_site_outcome("scoopwhoop.com", "coffee", kept=8, dropped=2)  # times_used=2

    r = si.discover_sites("coffee", call_fn=lambda p, m: LLM_JSON)
    by_domain = {s["domain"]: s for s in r["sites"]}
    assert by_domain["scoopwhoop.com"]["known"] is True
    assert by_domain["scoopwhoop.com"]["times_used"] == 2
    assert by_domain["scoopwhoop.com"]["confidence"] == 0.85  # 17/20
    # The LLM's OTHER candidate (never seen before) is still surfaced, just not "known".
    assert by_domain["food.ndtv.com"]["known"] is False
    assert by_domain["food.ndtv.com"]["needs_validation"] is True
    # No duplicate entry for scoopwhoop.com even though it also came back from the LLM.
    assert sum(1 for s in r["sites"] if s["domain"] == "scoopwhoop.com") == 1


def test_discover_sites_auto_trusts_only_with_enough_uses_and_confidence(fresh_db):
    # Only 1 use so far -> not auto-trusted yet, even with a perfect ratio.
    storage.record_site_outcome("newish.com", "coffee", kept=5, dropped=0)
    r = si.discover_sites("coffee", call_fn=lambda p, m: json.dumps({"sites": []}))
    row = next(s for s in r["sites"] if s["domain"] == "newish.com")
    assert row["needs_validation"] is True  # not enough history yet

    # Enough uses AND good confidence -> auto-trusted.
    for _ in range(si.MIN_USES_TO_AUTO_TRUST - 1):
        storage.record_site_outcome("newish.com", "coffee", kept=5, dropped=0)
    r = si.discover_sites("coffee", call_fn=lambda p, m: json.dumps({"sites": []}))
    row = next(s for s in r["sites"] if s["domain"] == "newish.com")
    assert row["needs_validation"] is False


def test_discover_sites_human_validation_overrides_low_history(fresh_db):
    storage.mark_site_validated("brandnew.com", "coffee")  # a human vouched, zero real uses yet
    r = si.discover_sites("coffee", call_fn=lambda p, m: json.dumps({"sites": []}))
    row = next(s for s in r["sites"] if s["domain"] == "brandnew.com")
    assert row["validated_by_human"] is True
    assert row["needs_validation"] is False


def test_discover_sites_requires_a_category():
    try:
        si.discover_sites("", call_fn=lambda p, m: LLM_JSON)
        assert False, "should have raised"
    except ValueError:
        pass


def test_confirm_sites_writes_to_the_ledger_and_is_the_only_thing_that_does(fresh_db):
    # discover_sites() itself must not have written anything.
    si.discover_sites("coffee", call_fn=lambda p, m: LLM_JSON)
    assert storage.get_site_intelligence("scoopwhoop.com", "coffee") is None

    r = si.confirm_sites("coffee", ["scoopwhoop.com", "food.ndtv.com"])
    assert r["count"] == 2
    row = storage.get_site_intelligence("scoopwhoop.com", "coffee")
    assert row is not None
    assert row["validated_by_human"] == 1
    assert row["times_suggested"] == 1


def test_confirm_sites_normalizes_domain_input(fresh_db):
    r = si.confirm_sites("coffee", ["https://www.Example.com/"])
    assert r["confirmed"] == ["example.com"]


def test_record_outcomes_updates_the_ledger_from_a_real_run(fresh_db):
    si.confirm_sites("coffee", ["scoopwhoop.com"])
    si.record_outcomes("coffee", [{"domain": "scoopwhoop.com", "kept": 7, "dropped": 3}])
    row = storage.get_site_intelligence("scoopwhoop.com", "coffee")
    assert row["times_used"] == 1
    assert row["confidence"] == 0.7


def test_record_outcomes_requires_a_category():
    try:
        si.record_outcomes("", [{"domain": "x.com", "kept": 1, "dropped": 0}])
        assert False, "should have raised"
    except ValueError:
        pass


def test_build_prompt_with_source_type_hint_focuses_the_search():
    p = si.build_prompt("coffee", source_type_hint="forums")
    assert "forums" in p.lower()
    assert "not news outlets in general" in p


def test_build_prompt_without_hint_stays_broad():
    p = si.build_prompt("coffee")
    assert "not just one type" in p


def test_discover_sites_passes_source_type_hint_into_the_prompt(fresh_db):
    captured = {}

    def fake_call(prompt, model):
        captured["prompt"] = prompt
        return LLM_JSON

    r = si.discover_sites("coffee", source_type_hint="lifestyle & food blogs", call_fn=fake_call)
    assert "lifestyle & food blogs" in captured["prompt"]
    assert r["source_type_hint"] == "lifestyle & food blogs"


FIND_SIMILAR_JSON = json.dumps({
    "sites": [
        {"name": "Times of India", "domain": "timesofindia.indiatimes.com", "source_type": "news",
         "why": "another mainstream national newspaper"},
        {"name": "The Hindu", "domain": "thehindu.com", "source_type": "news",
         "why": "another mainstream national newspaper"},
    ],
})


def test_find_similar_sites_returns_fresh_candidates_excluding_the_seed(fresh_db):
    r = si.find_similar_sites("hindustantimes.com", "coffee", call_fn=lambda p, m: FIND_SIMILAR_JSON)
    domains = {s["domain"] for s in r["sites"]}
    assert domains == {"timesofindia.indiatimes.com", "thehindu.com"}
    assert "hindustantimes.com" not in domains
    assert r["seed_domain"] == "hindustantimes.com"


def test_find_similar_sites_prompt_names_the_seed_domain():
    p = si.build_similar_sites_prompt("hindustantimes.com", "coffee")
    assert "hindustantimes.com" in p


def test_find_similar_sites_excludes_seed_even_if_llm_echoes_it_back(fresh_db):
    echoing = json.dumps({"sites": [
        {"name": "Hindustan Times", "domain": "hindustantimes.com", "source_type": "news"},
        {"name": "Times of India", "domain": "timesofindia.indiatimes.com", "source_type": "news"},
    ]})
    r = si.find_similar_sites("hindustantimes.com", "coffee", call_fn=lambda p, m: echoing)
    domains = {s["domain"] for s in r["sites"]}
    assert domains == {"timesofindia.indiatimes.com"}


def test_find_similar_sites_surfaces_ledger_track_record_for_a_returned_domain(fresh_db):
    storage.record_site_outcome("timesofindia.indiatimes.com", "coffee", kept=9, dropped=1)
    r = si.find_similar_sites("hindustantimes.com", "coffee", call_fn=lambda p, m: FIND_SIMILAR_JSON)
    toi = next(s for s in r["sites"] if s["domain"] == "timesofindia.indiatimes.com")
    assert toi["known"] is True
    assert toi["confidence"] == 0.9


def test_find_similar_sites_requires_a_seed_domain():
    try:
        si.find_similar_sites("", "coffee", call_fn=lambda p, m: FIND_SIMILAR_JSON)
        assert False, "should have raised"
    except ValueError:
        pass


def test_find_similar_sites_requires_a_category():
    try:
        si.find_similar_sites("hindustantimes.com", "", call_fn=lambda p, m: FIND_SIMILAR_JSON)
        assert False, "should have raised"
    except ValueError:
        pass
