"""Wizard generalization: URL building, source plan, no hard-coded brands."""
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
