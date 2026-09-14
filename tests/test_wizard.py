"""Wizard generalization: URL building, source plan, no hard-coded brands."""
import json
import urllib.parse

import config


def _parse_qs(url):
    parsed = urllib.parse.urlparse(url)
    return parsed, urllib.parse.parse_qs(parsed.query)


def test_google_news_url_arbitrary_combo():
    # Arbitrary (country, language, keyword) -> correct hl/gl/ceid triple.
    url = config.build_google_news_url(["widget delight"], "de", "DE")
    parsed, qs = _parse_qs(url)
    assert parsed.netloc == "news.google.com"
    assert parsed.path == "/rss/search"
    assert qs["hl"] == ["de-DE"]
    assert qs["gl"] == ["DE"]
    assert qs["ceid"] == ["DE:de"]
    # Multi-word term is phrase-quoted.
    assert qs["q"] == ['"widget delight"']


def test_google_news_url_singapore_english():
    url = config.build_google_news_url(["Acme Cola", "cola price"], "en", "SG")
    _, qs = _parse_qs(url)
    assert qs["hl"] == ["en-SG"]
    assert qs["gl"] == ["SG"]
    assert qs["ceid"] == ["SG:en"]
    assert qs["q"] == ['"Acme Cola" OR "cola price"']


def test_google_news_url_date_injection():
    url = config.build_google_news_url(["x"], "en", "US", after="2024-01-01", before="2024-02-01")
    _, qs = _parse_qs(url)
    assert "after:2024-01-01" in qs["q"][0]
    assert "before:2024-02-01" in qs["q"][0]


def test_resolve_country_known_and_unknown():
    sg = config.resolve_country("Singapore")
    assert sg["iso"] == "SG" and sg["gdelt"] == "SN"
    unknown = config.resolve_country("Atlantis")
    assert unknown["iso"] == "" and unknown.get("needs_confirmation") == "true"
    assert unknown["demonym"] == ""  # never fabricated for an unknown country


def test_demonyms_are_not_naive_substrings_of_the_country_name():
    """Real bug this fixes: for most countries the demonym is NOT a substring of the
    country name (France -> French), so a market filter relying on country-name-only
    substring matching silently misses demonym-only mentions ('the French government').
    Malaysia (-> Malaysian) worked by luck; these must be explicit, not derived."""
    cases = {"france": "French", "philippines": "Filipino", "uk": "British",
            "netherlands": "Dutch", "united kingdom": "British", "usa": "American"}
    for key, expected_demonym in cases.items():
        info = config.resolve_country(key)
        assert info["demonym"] == expected_demonym
        # Prove the naive substring approach would have failed for this one.
        assert info["name"].lower() not in expected_demonym.lower() or key == "malaysia"


def test_wizard_market_terms_include_both_name_and_demonym():
    cfg = config.run_wizard({
        "market": {"country": "France", "languages": ["en", "fr"]},
        "product": {"brand": "TestBrand", "category": "x", "category_type": "other"},
    })
    terms = cfg["market"]["market_terms"]
    assert "France" in terms and "French" in terms


def test_wizard_unknown_country_market_terms_dont_crash():
    cfg = config.run_wizard({
        "market": {"country": "Atlantis", "languages": ["en"]},
        "product": {"brand": "TestBrand", "category": "x", "category_type": "other"},
    })
    assert cfg["market"]["market_terms"] == ["Atlantis"]  # no fabricated demonym


def test_wizard_market_terms_include_native_script_country_name():
    """Real gap this closes: a native-script article (Telugu, Tamil, ...) essentially
    never contains the Latin-script "India"/"Indian", so without this it gets wrongly
    dropped as off-market even when genuinely India-published (verified live against
    real Telugu-language coffee articles from tv9telugu.com / ETV Bharat / Andhrajyothy)."""
    cfg = config.run_wizard({
        "market": {"country": "India", "languages": ["en", "te", "ta", "hi"]},
        "product": {"brand": "", "category": "coffee", "category_type": "fmcg_food"},
    })
    terms = cfg["market"]["market_terms"]
    assert "India" in terms and "Indian" in terms
    assert "భారత్" in terms  # Telugu
    assert "இந்தியா" in terms  # Tamil
    assert "भारत" in terms  # Hindi
    # Only the STUDY's configured languages contribute a native term — Gujarati wasn't
    # configured here, so its native name must not appear even though it's in the table.
    assert "ભારત" not in terms


def test_wizard_geo_scope_city_adds_value_to_market_terms():
    """DESIGN_01 §3: a city/state/region geo_scope needs no new matching mechanism — its
    value just becomes another market_term, reusing market_signal() unchanged."""
    cfg = config.run_wizard({
        "market": {"languages": ["en"],
                  "geo_scope": {"level": "city", "value": "Bangalore", "country": "India"}},
        "product": {"brand": "", "category": "coffee", "category_type": "fmcg_food"},
    })
    assert cfg["market"]["country"] == "India"  # country-level facts still resolve correctly
    assert cfg["market"]["country_code"] == "IN"
    terms = cfg["market"]["market_terms"]
    assert "India" in terms and "Indian" in terms
    assert "Bangalore" in terms
    assert cfg["market"]["geo_scope"] == {"level": "city", "value": "Bangalore", "country": "India"}


def test_wizard_geo_scope_country_level_does_not_duplicate_market_terms():
    cfg = config.run_wizard({
        "market": {"languages": ["en"],
                  "geo_scope": {"level": "country", "value": "India", "country": "India"}},
        "product": {"brand": "", "category": "coffee", "category_type": "fmcg_food"},
    })
    terms = cfg["market"]["market_terms"]
    assert terms.count("India") == 1  # not duplicated by geo_scope.value at country level


def test_wizard_without_geo_scope_has_no_geo_scope_key():
    # Backward compatibility: a plain intake (no geo_scope) produces config identical in
    # shape to before this feature existed -- no geo_scope key appears at all.
    cfg = config.run_wizard({
        "market": {"country": "India", "languages": ["en"]},
        "product": {"brand": "", "category": "coffee", "category_type": "fmcg_food"},
    })
    assert "geo_scope" not in cfg["market"]


def test_wizard_market_terms_native_name_absent_for_unconfigured_country():
    # A country with no native_names entry (everything except India, currently) must
    # degrade gracefully — no crash, no fabricated term.
    cfg = config.run_wizard({
        "market": {"country": "Malaysia", "languages": ["en", "zh"]},
        "product": {"brand": "Maggi", "category": "instant noodles", "category_type": "fmcg_food"},
    })
    assert cfg["market"]["market_terms"] == ["Malaysia", "Malaysian"]


def test_bing_news_url_builder():
    url = config.build_bing_news_url(["Acme Cola", "cola price"], "en-SG")
    parsed, qs = _parse_qs(url)
    assert parsed.netloc == "www.bing.com"
    assert parsed.path == "/news/search"
    assert qs["format"] == ["RSS"]
    assert qs["q"] == ['"Acme Cola" OR "cola price"']
    assert qs["setmkt"] == ["en-SG"]


def test_wizard_generates_both_google_and_bing_feeds():
    """Structural gap #4: relying on Google News alone means anything its index missed
    is invisible. Bing News is a second, independent, no-API-key index — the wizard
    must generate it alongside Google News automatically, not as a manual add-on."""
    cfg = config.run_wizard({
        "market": {"country": "Malaysia", "languages": ["en"]},
        "product": {"brand": "Maggi", "category": "instant noodles", "category_type": "fmcg_food"},
        "competitors": [],
    })
    gn = cfg["source_plan"]["google_news_feeds"]
    bing = cfg["source_plan"]["bing_news_feeds"]
    assert len(gn) > 0 and len(bing) > 0
    assert len(gn) == len(bing)  # same keyword-structure coverage on both indexes
    assert all(f["url"].startswith("https://www.bing.com/news/search?") for f in bing)


def test_wizard_end_to_end_no_hardcoded_brand():
    intake = {
        "market": {"country": "Singapore", "languages": ["en", "zh"]},
        "product": {"brand": "Acme Cola", "category": "carbonated soft drinks",
                    "category_type": "fmcg_food"},
        "competitors": ["Fizzly", "PopMax"],
        "keywords": {"trend_terms": ["sugar-free", "local flavor"]},
    }
    cfg = config.run_wizard(intake)
    assert cfg["market"]["country_code"] == "SG"
    assert cfg["market"]["gdelt_country"] == "SN"
    # Relevance terms derived from brand + competitors + category tokens.
    rt = [t.lower() for t in cfg["relevance_terms"]]
    assert "acme cola" in rt and "fizzly" in rt and "popmax" in rt
    # FMCG -> delivery/quick-commerce segment enabled.
    assert cfg["source_plan"]["segments"]["delivery_quick_commerce"] is True
    # Google News feeds were generated for the seeded English structures.
    feeds = cfg["source_plan"]["google_news_feeds"]
    assert any(f["language"] == "en" for f in feeds)
    assert all(f["url"].startswith("https://news.google.com/rss/search?") for f in feeds)
    # GDELT sourcecountry present.
    assert cfg["source_plan"]["gdelt"]["sourcecountry"] == "SN"
    # Tier-3 gaps documented.
    platforms = [g["platform"] for g in cfg["source_plan"]["tier3_gaps"]]
    assert "Instagram" in platforms and "LinkedIn" in platforms


def test_wizard_b2b_disables_delivery_enables_tradepress():
    intake = {
        "market": {"country": "Germany", "languages": ["de"]},
        "product": {"brand": "IndustCorp", "category": "industrial valves",
                    "category_type": "b2b_industrial"},
        "competitors": [],
    }
    cfg = config.run_wizard(intake)
    seg = cfg["source_plan"]["segments"]
    assert seg["delivery_quick_commerce"] is False
    assert seg["b2b_trade_press"] is True


def test_wizard_scaffolds_empty_native_language_slots():
    intake = {
        "market": {"country": "India", "languages": ["en", "hi"]},
        "product": {"brand": "Zeta", "category": "instant noodles", "category_type": "fmcg_food"},
        "competitors": [],
    }
    cfg = config.run_wizard(intake)
    by_lang = cfg["keywords"]["by_language"]
    # Secondary language present but with empty slots for the user to fill natively.
    assert "hi" in by_lang
    assert by_lang["hi"]["brand"] == []
    # Primary language seeded from intake only.
    assert by_lang["en"]["brand"] == ["Zeta"]


def test_regenerate_news_feeds_reflects_edited_keywords():
    """PUT /config alone does not recompute derived feed lists — regenerate_news_feeds()
    is what Source Plan keyword edits must go through so the News scraper (which reads
    the stored feed list, not keywords.by_language, at collect time) actually sees them."""
    cfg = config.run_wizard({
        "market": {"country": "India", "languages": ["en"]},
        "product": {"brand": "", "category": "coffee", "category_type": "fmcg_food"},
    })
    assert len(cfg["source_plan"]["google_news_feeds"]) == 1  # just "coffee" so far

    # Simulate a Source Plan edit: add more terms to the SAME existing structure...
    edited = json.loads(json.dumps(cfg))  # deep copy, like the frontend does
    edited["keywords"]["by_language"]["en"]["category_generic"] = ["coffee", "latte", "americano"]
    regenerated = config.regenerate_news_feeds(edited)
    gf = regenerated["source_plan"]["google_news_feeds"]
    # ...still exactly ONE feed (one per language+structure) — broadened OR-query, not
    # more feeds. This is the exact mechanic that limits volume from just adding synonyms
    # to an existing slot.
    assert len(gf) == 1
    assert gf[0]["query"] == "coffee OR latte OR americano"

    # ...versus adding a NEW structure key entirely -> a genuinely separate feed with its
    # own ~100-result ceiling.
    edited["keywords"]["by_language"]["en"]["category_generic_cold"] = ["cold coffee"]
    regenerated2 = config.regenerate_news_feeds(edited)
    assert len(regenerated2["source_plan"]["google_news_feeds"]) == 2

    # Original config object must not be mutated.
    assert len(cfg["source_plan"]["google_news_feeds"]) == 1


def test_regenerate_news_feeds_preserves_other_source_plan_keys():
    cfg = config.run_wizard({
        "market": {"country": "Malaysia", "languages": ["en"]},
        "product": {"brand": "Maggi", "category": "instant noodles", "category_type": "fmcg_food"},
    })
    cfg["source_plan"]["ecommerce_urls"] = ["https://example.com/search?q=maggi"]
    regenerated = config.regenerate_news_feeds(cfg)
    assert regenerated["source_plan"]["ecommerce_urls"] == ["https://example.com/search?q=maggi"]


def test_list_countries_dedupes_aliases_and_is_sorted():
    """Backs the intake wizard's country/region picker. COUNTRY_TABLE has alias keys
    ("usa" and "united states" both resolve to the same country) — the picker must not
    show the same country twice."""
    countries = config.list_countries()
    names = [c["name"] for c in countries]
    assert len(names) == len(set(names))  # no duplicates despite alias keys
    assert names == sorted(names)  # alphabetical for scanning
    assert "United States" in names and "usa" not in names and "United Kingdom" in names
    malaysia = next(c for c in countries if c["name"] == "Malaysia")
    assert malaysia["iso"] == "MY"


def test_is_language_country_exclusive_enough():
    assert config.is_language_country_exclusive_enough("te") is True   # Telugu
    assert config.is_language_country_exclusive_enough("ta") is True   # Tamil
    assert config.is_language_country_exclusive_enough("en") is False  # global
    assert config.is_language_country_exclusive_enough("es") is False  # global
    assert config.is_language_country_exclusive_enough("") is False    # unknown -> no bypass
    assert config.is_language_country_exclusive_enough("EN") is False  # case-insensitive


def test_list_languages_is_a_defensive_copy():
    """Backs the intake wizard's language dropdown. Must return a fresh copy each call —
    a caller mutating the result must never corrupt the module-level reference table."""
    langs = config.list_languages()
    assert len(langs) > 20
    codes = [l["code"] for l in langs]
    assert len(codes) == len(set(codes))  # no duplicate codes
    langs.append({"code": "xx", "name": "Bogus"})
    langs[0]["name"] = "Tampered"
    fresh = config.list_languages()
    assert {"code": "xx", "name": "Bogus"} not in fresh
    assert fresh[0]["name"] != "Tampered"


def test_wizard_category_only_no_brand():
    """A category-wide study (e.g. "instant noodles in Malaysia") with no single target
    brand must produce a fully usable config — not a degraded/broken one. This is what
    lets a search be scoped to a product category alone."""
    intake = {
        "market": {"country": "Malaysia", "languages": ["en", "ms"]},
        "product": {"brand": "", "category": "instant noodles", "category_type": "fmcg_food"},
        "competitors": ["Indomie"],
        "keywords": {"trend_terms": ["spicy"]},
    }
    cfg = config.run_wizard(intake)
    assert cfg["product"]["brand"] == ""
    # Relevance terms still populated: category tokens + competitors, just no brand token.
    rt = [t.lower() for t in cfg["relevance_terms"]]
    assert "instant" in rt and "noodles" in rt and "indomie" in rt
    # Keyword scaffold: brand-derived slots stay empty, category_generic still seeded.
    en_slots = cfg["keywords"]["by_language"]["en"]
    assert en_slots["brand"] == [] and en_slots["brand_price"] == [] and en_slots["brand_complaint"] == []
    assert en_slots["category_generic"] == ["instant noodles"]
    # Google Business query needs a named entity — correctly left empty, not "  Malaysia".
    assert cfg["source_plan"]["google_business"]["query"] == ""
    # Trends still gets keywords (falls back to relevance_terms when no trend-specific ones apply).
    assert cfg["source_plan"]["trends"]["keywords"] == ["spicy"]


def test_suggest_subreddits_leads_with_the_category_itself():
    """Real bug found live (user report: "95% of reddit links are not useful. Why not
    going into coffee related communities for india"): the old version never looked
    at the actual category text at all -- only the broad category_type bucket
    ("fmcg_food" -> food/Cooking/grocery/snacks) and the country name, so a coffee
    study never got r/Coffee (a real, active, ~2M-member subreddit, confirmed live)
    suggested at all. The category-derived guess must come first (highest-confidence
    candidate)."""
    out = config.suggest_subreddits("India", "fmcg_food", "coffee")
    assert out[0] == "coffee"
    assert "india" in out and "food" in out  # existing country/category_type patterns still present


def test_suggest_subreddits_includes_country_category_compounds_both_orderings():
    """Follow-up gap found live (user report: "there are indian coffee communities
    like coffeeindia, indiacoffee"): both orderings are REAL, confirmed live --
    r/coffeeindia's own subtitle is "This community is dedicated to the coffee
    community in India...", and r/IndiaCoffee responds live too -- but neither
    ordering was ever guessed; the bare category and bare country were only ever
    tried separately, never joined. Both compounds must appear, ranked ahead of the
    generic category_type patterns (right after the bare category guess)."""
    out = config.suggest_subreddits("India", "fmcg_food", "coffee")
    assert "coffeeindia" in out
    assert "indiacoffee" in out
    assert out.index("coffeeindia") < out.index("food")
    assert out.index("indiacoffee") < out.index("food")


def test_suggest_subreddits_compounds_need_both_category_and_country():
    # No country -> no compound guess possible, no crash either.
    out = config.suggest_subreddits("", "fmcg_food", "coffee")
    assert out[0] == "coffee"
    assert not any("coffee" in c and c != "coffee" for c in out)


def test_suggest_subreddits_category_slug_strips_spaces_and_punctuation():
    """Reddit subreddit names are alphanumeric-only -- a multi-word category must
    still produce a single, real-looking candidate (e.g. r/electricscooters, itself
    a real subreddit), not something with spaces that could never be a valid name."""
    out = config.suggest_subreddits("Vietnam", "other", "Electric Scooters!")
    assert out[0] == "electricscooters"


def test_suggest_subreddits_with_no_category_behaves_exactly_as_before():
    """Purely additive -- omitting category (every pre-existing call site before
    this fix) must not change behavior."""
    out = config.suggest_subreddits("India", "fmcg_food")
    assert out == ["india", "indiafire", "food", "Cooking", "grocery", "snacks"]


def test_suggest_subreddits_dedupes_category_against_existing_patterns():
    """If the category text happens to already match a country/category_type
    pattern, it must not appear twice."""
    out = config.suggest_subreddits("India", "fmcg_food", "food")
    assert out.count("food") == 1


def test_wizard_subreddits_include_the_category_via_run_wizard():
    """End-to-end: run_wizard() actually passes the category through, not just the
    unit function in isolation."""
    intake = {
        "market": {"country": "India", "languages": ["en"]},
        "product": {"brand": "", "category": "coffee", "category_type": "fmcg_food"},
    }
    cfg = config.run_wizard(intake)
    assert cfg["source_plan"]["subreddits"][0] == "coffee"
