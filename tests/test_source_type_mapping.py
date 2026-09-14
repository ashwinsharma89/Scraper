"""Category -> source-type mapping, Layer 1 (LLM) + Layer 2 (keyword routing)
(DESIGN_01 §2)."""
import json

import source_type_mapping as stm

LLM_JSON = json.dumps({
    "source_types": [
        {"name": "News coverage", "why": "mainstream press covers coffee culture"},
        {"name": "Lifestyle & food blogs", "why": "dedicated coffee/café content"},
        {"name": "Reddit discussions", "why": "community opinions"},
        {"name": "Café/venue listing sites", "why": "no existing channel fetches these"},
    ],
})


def test_route_source_type_matches_existing_channels():
    assert stm.route_source_type("News coverage") == {"strategy": "existing_channel", "channel": "news"}
    assert stm.route_source_type("Reddit discussions")["channel"] == "reddit"
    assert stm.route_source_type("Local forums") == {"strategy": "existing_channel", "channel": "forums"}
    assert stm.route_source_type("YouTube reviews")["channel"] == "youtube"


def test_route_source_type_falls_back_to_generic_site_discovery():
    r = stm.route_source_type("Lifestyle & food blogs")
    assert r == {"strategy": "generic_site_discovery", "channel": None}
    r2 = stm.route_source_type("Café/venue listing sites")
    assert r2["strategy"] == "generic_site_discovery"


def test_route_source_type_handles_empty_name():
    assert stm.route_source_type("")["strategy"] == "generic_site_discovery"


def test_route_source_type_flags_tier3_platforms_as_unsupported_not_generic_site():
    """Real bug found live: 'Instagram & visual social platforms' and 'WhatsApp groups
    & Telegram channels' (genuine LLM output) were falling through to
    generic_site_discovery, which can never work for app-only platforms with no
    public sitemap of individual posts -- CLAUDE.md's own documented, permanent
    Tier-3 gap. Must be flagged honestly, not silently routed somewhere that will
    just quietly find nothing."""
    assert stm.route_source_type("Instagram & visual social platforms") == {
        "strategy": "unsupported", "channel": None}
    assert stm.route_source_type("WhatsApp groups & Telegram channels")["strategy"] == "unsupported"
    assert stm.route_source_type("TikTok trends")["strategy"] == "unsupported"


def test_route_source_type_a_real_channel_mention_wins_over_a_tier3_one_in_the_same_name():
    """Real gap, user feedback: "don't need whatsapp groups but need forums." A
    compound suggestion naming BOTH a real channel and a Tier-3 platform must keep
    the real one, not lose it to an all-or-nothing Tier-3 veto."""
    r = stm.route_source_type("Niche coffee enthusiast forums & WhatsApp groups")
    assert r == {"strategy": "existing_channel", "channel": "forums"}


def test_route_source_type_pure_tier3_with_no_channel_mention_still_unsupported():
    assert stm.route_source_type("WhatsApp groups only")["strategy"] == "unsupported"


def test_route_source_type_catches_facebook_phrased_as_a_full_sentence():
    """Real gap found live via Increment 9 generalization testing (skincare/Brazil):
    Layer 1 phrased it as "Facebook beauty & skincare groups & communities" -- the
    old "facebook group" contiguous-phrase keyword never matches that, so it silently
    fell through to generic_site_discovery, a pipeline that can never work for a
    login-walled Facebook group. Matching bare "facebook" (like instagram/whatsapp/
    telegram/tiktok already do) catches this and any other real phrasing."""
    r = stm.route_source_type("Facebook beauty & skincare groups & communities")
    assert r["strategy"] == "unsupported"


def test_route_source_type_facebook_still_yields_to_a_real_channel_mention():
    r = stm.route_source_type("YouTube and Facebook video content")
    assert r == {"strategy": "existing_channel", "channel": "youtube"}


def test_route_source_type_tiktok_is_not_misrouted_to_youtube_via_bare_video():
    """Real bug found live via Increment 9 generalization testing (electric scooters/
    Vietnam): "TikTok & short-form video platforms" matched the bare "video" keyword
    and incorrectly routed to the YouTube channel -- YouTube's Data API has zero
    applicability to TikTok content, and "tiktok" is itself a genuine Tier-3 keyword
    that the generic "video" match was silently overriding."""
    r = stm.route_source_type("TikTok & short-form video platforms")
    assert r == {"strategy": "unsupported", "channel": None}


def test_route_source_type_generic_video_mention_with_no_platform_name_is_generic_site():
    """"video" alone, naming no platform at all, is genuinely ambiguous -- it must NOT
    silently claim the youtube channel just because a category mentions video content."""
    r = stm.route_source_type("Product video reviews and demos")
    assert r["strategy"] == "generic_site_discovery"


def test_suggest_source_types_routes_every_candidate():
    r = stm.suggest_source_types("coffee", call_fn=lambda p, m: LLM_JSON)
    by_name = {s["name"]: s for s in r["source_types"]}
    assert by_name["News coverage"]["strategy"] == "existing_channel"
    assert by_name["News coverage"]["channel"] == "news"
    assert by_name["Reddit discussions"]["channel"] == "reddit"
    assert by_name["Lifestyle & food blogs"]["strategy"] == "generic_site_discovery"
    assert by_name["Café/venue listing sites"]["strategy"] == "generic_site_discovery"
    assert r["_summary"]["existing_channel"] == 2
    assert r["_summary"]["generic_site_discovery"] == 2


def test_suggest_source_types_requires_a_category():
    try:
        stm.suggest_source_types("", call_fn=lambda p, m: LLM_JSON)
        assert False, "should have raised"
    except ValueError:
        pass


def test_parse_source_types_dedupes_case_insensitively():
    raw = json.dumps({"source_types": [{"name": "News"}, {"name": "news"}]})
    types = stm.parse_source_types(raw)
    assert len(types) == 1


def test_parse_source_types_empty_response_raises():
    try:
        stm.parse_source_types("")
        assert False, "should have raised"
    except ValueError:
        pass
