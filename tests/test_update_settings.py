"""config.update_settings() — editing a study's market/brand/competitors after
creation (HANDOFF §7 item 3: "today the market is only set at wizard time")."""
import config


def _base_config():
    return config.run_wizard({
        "market": {"country": "India", "languages": ["en"]},
        "product": {"brand": "Acme Cola", "category": "cola", "category_type": "fmcg_food"},
        "competitors": ["Rival Cola"],
    })


def test_update_settings_overwrites_market_country_and_recomputes_iso_facts():
    cfg = _base_config()
    new_cfg = config.update_settings(
        cfg,
        market={"country": "Malaysia", "languages": ["en"]},
        product=cfg["product"],
        competitors=cfg["competitors"],
    )
    assert new_cfg["market"]["country"] == "Malaysia"
    assert new_cfg["market"]["country_code"] == "MY"
    assert new_cfg["market"]["cctld"] == ".my"
    assert "Malaysia" in new_cfg["market"]["market_terms"]
    assert "Malaysian" in new_cfg["market"]["market_terms"]


def test_update_settings_preserves_user_added_rss_feeds_and_forum_urls():
    """The whole point of this function: fields with no mechanical counterpart must
    survive an edit untouched, unlike run_wizard() which would wipe them by rebuilding
    from a blank intake."""
    cfg = _base_config()
    cfg["source_plan"]["rss_feeds"] = ["https://example.com/feed.xml"]
    cfg["source_plan"]["forum_urls"] = ["https://forum.example.com/thread/1"]
    cfg["source_plan"]["ecommerce_urls"] = ["https://shop.example.com/p/1"]

    new_cfg = config.update_settings(
        cfg, market={"country": "Malaysia", "languages": ["en"]},
        product=cfg["product"], competitors=cfg["competitors"],
    )
    assert new_cfg["source_plan"]["rss_feeds"] == ["https://example.com/feed.xml"]
    assert new_cfg["source_plan"]["forum_urls"] == ["https://forum.example.com/thread/1"]
    assert new_cfg["source_plan"]["ecommerce_urls"] == ["https://shop.example.com/p/1"]


def test_update_settings_preserves_hand_edited_keyword_structures_for_existing_language():
    cfg = _base_config()
    cfg["keywords"]["by_language"]["en"]["category_generic"] = ["cola", "soft drink", "fizzy drink"]

    new_cfg = config.update_settings(
        cfg, market={"country": "India", "languages": ["en"]},
        product={"brand": "Acme Cola", "category": "cola", "category_type": "fmcg_food"},
        competitors=["Rival Cola", "Second Rival"],
    )
    assert new_cfg["keywords"]["by_language"]["en"]["category_generic"] == \
        ["cola", "soft drink", "fizzy drink"]


def test_update_settings_scaffolds_empty_slots_for_a_newly_added_language():
    cfg = _base_config()
    new_cfg = config.update_settings(
        cfg, market={"country": "India", "languages": ["en", "hi"]},
        product=cfg["product"], competitors=cfg["competitors"],
    )
    assert new_cfg["keywords"]["by_language"]["hi"] == {
        "brand": [], "brand_price": [], "category_generic": [], "brand_complaint": []}
    # The original (primary) language's real, brand-seeded structure is untouched.
    assert new_cfg["keywords"]["by_language"]["en"]["brand"] == ["Acme Cola"]


def test_update_settings_merges_market_terms_instead_of_replacing():
    """A city/region the user added by hand in Source plan (not derivable from country
    facts alone) must survive an edit to brand/competitors that leaves country
    unchanged."""
    cfg = _base_config()
    cfg["market"]["market_terms"].append("Bangalore")

    new_cfg = config.update_settings(
        cfg, market={"country": "India", "languages": ["en"]},
        product={"brand": "Acme Cola", "category": "cola", "category_type": "fmcg_food"},
        competitors=["Rival Cola", "New Rival"],
    )
    assert "Bangalore" in new_cfg["market"]["market_terms"]
    assert "India" in new_cfg["market"]["market_terms"]


def test_update_settings_merges_subreddits_instead_of_replacing():
    cfg = _base_config()
    cfg["source_plan"]["subreddits"].append("mycustomsub")

    new_cfg = config.update_settings(
        cfg, market={"country": "India", "languages": ["en"]},
        product=cfg["product"], competitors=cfg["competitors"],
    )
    assert "mycustomsub" in new_cfg["source_plan"]["subreddits"]


def test_update_settings_overwrites_competitors_list_directly():
    """Unlike market_terms/subreddits (which get contributions from multiple
    features), competitors has exactly one editing surface — this form — so a
    real removal here is a deliberate edit, not accidental data loss."""
    cfg = _base_config()
    new_cfg = config.update_settings(
        cfg, market={"country": "India", "languages": ["en"]},
        product=cfg["product"], competitors=["Totally Different Rival"],
    )
    assert new_cfg["competitors"] == ["Totally Different Rival"]


def test_update_settings_drops_stale_geo_scope_when_country_changes():
    cfg = config.run_wizard({
        "market": {"country": "India", "languages": ["en"],
                  "geo_scope": {"level": "city", "value": "Bangalore", "country": "India"}},
        "product": {"brand": "Acme Cola", "category": "cola", "category_type": "fmcg_food"},
    })
    assert cfg["market"]["geo_scope"]["value"] == "Bangalore"

    new_cfg = config.update_settings(
        cfg, market={"country": "Malaysia", "languages": ["en"]},
        product=cfg["product"], competitors=[],
    )
    assert "geo_scope" not in new_cfg["market"]


def test_update_settings_keeps_geo_scope_when_country_unchanged():
    cfg = config.run_wizard({
        "market": {"country": "India", "languages": ["en"],
                  "geo_scope": {"level": "city", "value": "Bangalore", "country": "India"}},
        "product": {"brand": "Acme Cola", "category": "cola", "category_type": "fmcg_food"},
    })
    new_cfg = config.update_settings(
        cfg, market={"country": "India", "languages": ["en"]},
        product={"brand": "Acme Cola 2.0", "category": "cola", "category_type": "fmcg_food"},
        competitors=[],
    )
    assert new_cfg["market"]["geo_scope"]["value"] == "Bangalore"


def test_update_settings_recomputes_google_and_bing_news_feeds():
    """Existing keyword structures (and therefore their query text) are preserved
    untouched by design -- see test_update_settings_preserves_hand_edited_keyword_
    structures_for_existing_language -- but the feed URLs themselves must still be
    rebuilt so a market change (which changes hl/gl/ceid) actually takes effect,
    matching regenerate_news_feeds()'s existing contract."""
    cfg = _base_config()
    old_feed_count = len(cfg["source_plan"]["google_news_feeds"])
    assert any("hl=en-IN" in f["url"] for f in cfg["source_plan"]["google_news_feeds"])

    new_cfg = config.update_settings(
        cfg, market={"country": "Malaysia", "languages": ["en"]},
        product=cfg["product"], competitors=cfg["competitors"],
    )
    # Same structures (brand name unchanged) -> same feed count, not silently zeroed.
    assert len(new_cfg["source_plan"]["google_news_feeds"]) == old_feed_count
    assert any("hl=en-MY" in f["url"] for f in new_cfg["source_plan"]["google_news_feeds"])
    assert not any("hl=en-IN" in f["url"] for f in new_cfg["source_plan"]["google_news_feeds"])


def test_update_settings_recomputes_category_type_dependent_segments():
    cfg = _base_config()
    assert cfg["source_plan"]["segments"]["delivery_quick_commerce"] is True  # fmcg_food

    new_cfg = config.update_settings(
        cfg, market={"country": "India", "languages": ["en"]},
        product={"brand": "Acme Cola", "category": "cola", "category_type": "b2b_industrial"},
        competitors=[],
    )
    assert new_cfg["source_plan"]["segments"]["delivery_quick_commerce"] is False
    assert new_cfg["source_plan"]["segments"]["b2b_trade_press"] is True


def test_update_settings_does_not_mutate_the_input_config():
    cfg = _base_config()
    original_country = cfg["market"]["country"]
    config.update_settings(
        cfg, market={"country": "Malaysia", "languages": ["en"]},
        product=cfg["product"], competitors=cfg["competitors"],
    )
    assert cfg["market"]["country"] == original_country
