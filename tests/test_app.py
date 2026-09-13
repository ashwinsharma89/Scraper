"""API surface: team mode rejects unauthenticated; solo allows; end-to-end happy path."""
import os

import pytest
from fastapi.testclient import TestClient

import app as app_mod
import auth
import storage


@pytest.fixture
def client(fresh_db):
    return TestClient(app_mod.app)


def _intake():
    return {
        "market": {"country": "Singapore", "languages": ["en"]},
        "product": {"brand": "Acme Cola", "category": "cola", "category_type": "fmcg_food"},
        "competitors": ["Fizzly"],
        "keywords": {"trend_terms": ["sugar-free"]},
    }


def test_solo_mode_allows_unauthenticated(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []
    # Wizard creates a project.
    r = client.post("/api/projects/wizard", json=_intake())
    assert r.status_code == 200
    assert r.json()["config"]["market"]["country_code"] == "SG"


def test_wizard_rejects_study_with_neither_brand_nor_category(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["product"] = {"brand": "", "category": "", "category_type": "fmcg_food"}
    r = client.post("/api/projects/wizard", json=intake)
    assert r.status_code == 400
    assert "brand" in r.json()["detail"].lower()


def test_wizard_allows_category_only_study_with_no_brand(client, monkeypatch):
    # A category-wide study (e.g. "instant noodles in Malaysia") with no single target
    # brand must be creatable — brand is an optional anchor, not a required one.
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["product"] = {"brand": "", "category": "instant noodles", "category_type": "fmcg_food"}
    r = client.post("/api/projects/wizard", json=intake)
    assert r.status_code == 200
    body = r.json()
    assert body["config"]["product"]["brand"] == ""
    assert body["config"]["product"]["category"] == "instant noodles"
    # Name falls back to category when brand is absent, not "Untitled study".
    assert body["name"] == "instant noodles"
    # Relevance terms still get populated from the category alone.
    assert any("instant" in t.lower() or "noodles" in t.lower()
               for t in body["config"]["relevance_terms"])


def test_team_mode_rejects_unauthenticated(client, monkeypatch):
    monkeypatch.setenv("MODE", "team")
    for path in ["/api/projects", "/api/projects/1", "/api/channels"]:
        r = client.get(path)
        assert r.status_code == 401, f"{path} should require auth in team mode"
    # Mutating routes also gated.
    r = client.post("/api/projects/wizard", json=_intake())
    assert r.status_code == 401


def test_team_mode_allows_after_login(client, monkeypatch):
    monkeypatch.setenv("MODE", "team")
    auth.create_user("alice", "pw", is_admin=True)
    # Unauthenticated -> 401.
    assert client.get("/api/projects").status_code == 401
    # Login sets the session cookie on the client.
    r = client.post("/api/auth/login", json={"username": "alice", "password": "pw"})
    assert r.status_code == 200
    r = client.get("/api/projects")
    assert r.status_code == 200
    # Bad password rejected.
    c2 = TestClient(app_mod.app)
    assert c2.post("/api/auth/login", json={"username": "alice", "password": "no"}).status_code == 401


def test_version_and_mode_endpoints(client):
    from version import __version__
    r = client.get("/api/version")
    assert r.json()["version"] == __version__


def test_static_assets_are_never_cached(client):
    # A no-build-step SPA under active iteration must never let a browser silently serve
    # a stale app.js/index.html after a code change (an empty dropdown with no error is
    # exactly what that looks like — this bit us live once already).
    r = client.get("/")
    assert r.headers.get("cache-control") == "no-store"
    r = client.get("/static/app.js")
    assert r.headers.get("cache-control") == "no-store"


def test_reference_languages_backs_the_wizard_dropdown(client, monkeypatch):
    # Powers the intake wizard's single/multi-select language picker.
    monkeypatch.setenv("MODE", "solo")
    r = client.get("/api/reference/languages")
    assert r.status_code == 200
    langs = r.json()
    assert len(langs) > 20
    codes = {l["code"] for l in langs}
    names = {l["code"]: l["name"] for l in langs}
    assert {"en", "zh", "ms", "ta", "hi", "es", "fr"} <= codes
    assert names["en"] == "English"
    # No dupes, every row has both fields.
    assert len(codes) == len(langs)
    assert all(l.get("code") and l.get("name") for l in langs)


def test_reference_countries_backs_the_wizard_dropdown(client, monkeypatch):
    # Powers the intake wizard's single/multi-select country/region picker.
    monkeypatch.setenv("MODE", "solo")
    r = client.get("/api/reference/countries")
    assert r.status_code == 200
    countries = r.json()
    names = [c["name"] for c in countries]
    assert len(names) == len(set(names))  # deduped despite COUNTRY_TABLE alias keys
    assert "Malaysia" in names and "United States" in names


def test_wizard_rejects_more_than_one_country(client, monkeypatch):
    # The picker's control allows multi-select for interaction consistency with
    # languages, but a study targets exactly one market — enforced server-side too.
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["market"]["country"] = ["Malaysia", "Singapore"]
    r = client.post("/api/projects/wizard", json=intake)
    assert r.status_code == 400
    assert "one country" in r.json()["detail"].lower()


def test_wizard_accepts_single_country_as_a_one_item_list(client, monkeypatch):
    # The frontend always submits country as a list (from the multi-select); a
    # single-item list is the normal case and must be normalized to a plain string.
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["market"]["country"] = ["Malaysia"]
    r = client.post("/api/projects/wizard", json=intake)
    assert r.status_code == 200
    assert r.json()["config"]["market"]["country"] == "Malaysia"


def test_wizard_rejects_empty_country(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["market"]["country"] = ""
    r = client.post("/api/projects/wizard", json=intake)
    assert r.status_code == 400
    assert "country" in r.json()["detail"].lower()


def test_wizard_accepts_city_level_geo_scope(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["market"] = {"languages": ["en"],
                        "geo_scope": {"level": "city", "value": "Bangalore", "country": "India"}}
    r = client.post("/api/projects/wizard", json=intake)
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert cfg["market"]["country"] == "India"
    assert cfg["market"]["geo_scope"]["value"] == "Bangalore"
    assert "Bangalore" in cfg["market"]["market_terms"]


def test_wizard_rejects_invalid_geo_scope_level(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["market"] = {"languages": ["en"],
                        "geo_scope": {"level": "planet", "value": "Earth", "country": "India"}}
    r = client.post("/api/projects/wizard", json=intake)
    assert r.status_code == 400
    assert "geo_scope.level" in r.json()["detail"]


def test_wizard_rejects_state_level_geo_scope_without_country(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["market"] = {"languages": ["en"],
                        "geo_scope": {"level": "state", "value": "Karnataka"}}  # no country
    r = client.post("/api/projects/wizard", json=intake)
    assert r.status_code == 400
    assert "country" in r.json()["detail"].lower()


def test_wizard_rejects_geo_scope_that_is_not_an_object(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["market"] = {"languages": ["en"], "geo_scope": "Bangalore"}
    r = client.post("/api/projects/wizard", json=intake)
    assert r.status_code == 400


def test_classify_category_endpoint(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    import category_discovery
    monkeypatch.setattr(category_discovery, "classify_category",
                        lambda term, geo_scope=None, **kw: {
                            "category": "coffee / food & beverage lifestyle",
                            "confidence": 0.9, "reasoning": "x",
                            "structured_data_hint": None, "needs_confirmation": False,
                        })
    r = client.post("/api/discovery/classify-category", json={"term": "coffee"})
    assert r.status_code == 200
    assert r.json()["category"] == "coffee / food & beverage lifestyle"


def test_classify_category_endpoint_400_on_empty_term(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    r = client.post("/api/discovery/classify-category", json={"term": ""})
    assert r.status_code == 400


def test_discover_sites_endpoint(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    import site_intelligence
    monkeypatch.setattr(site_intelligence, "discover_sites",
                        lambda category, geo_scope=None, **kw: {
                            "category": category,
                            "sites": [{"name": "ScoopWhoop", "domain": "scoopwhoop.com",
                                      "known": False, "needs_validation": True}],
                            "_summary": {"total": 1, "known": 0, "needs_validation": 1},
                        })
    r = client.post("/api/discovery/sites", json={"category": "coffee"})
    assert r.status_code == 200
    assert r.json()["sites"][0]["domain"] == "scoopwhoop.com"


def test_confirm_sites_endpoint_actually_writes_to_the_ledger(client, monkeypatch):
    # No mocking here -- exercise the real storage write through the real endpoint.
    monkeypatch.setenv("MODE", "solo")
    r = client.post("/api/discovery/confirm-sites",
                    json={"category": "coffee", "domains": ["scoopwhoop.com"]})
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert storage.get_site_intelligence("scoopwhoop.com", "coffee")["validated_by_human"] == 1


def test_confirm_sites_endpoint_400_on_empty_category(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    r = client.post("/api/discovery/confirm-sites", json={"category": "", "domains": ["x.com"]})
    assert r.status_code == 400


def test_regenerate_feeds_picks_up_edited_keywords(client, monkeypatch):
    # PUT /config alone does not recompute feeds — this endpoint is what Source Plan
    # keyword edits must go through for the News scraper to actually see them.
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["product"] = {"brand": "", "category": "cola", "category_type": "fmcg_food"}
    r = client.post("/api/projects/wizard", json=intake)
    pid = r.json()["id"]
    cfg = r.json()["config"]
    assert len(cfg["source_plan"]["google_news_feeds"]) == 1  # just category_generic

    # Add a whole new keyword structure (separate feed, separate ~100-result ceiling).
    cfg["keywords"]["by_language"]["en"]["category_generic_diet"] = ["diet cola"]
    client.put(f"/api/projects/{pid}/config", json={"config": cfg})

    r2 = client.post(f"/api/projects/{pid}/regenerate-feeds")
    assert r2.status_code == 200
    assert r2.json()["google_news_feeds"] == 2

    r3 = client.get(f"/api/projects/{pid}")
    assert len(r3.json()["config"]["source_plan"]["google_news_feeds"]) == 2


def test_suggest_terms_defaults_to_project_category(client, monkeypatch):
    # No "term" in the body -> falls back to the project's own category.
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["product"] = {"brand": "", "category": "cola", "category_type": "fmcg_food"}
    r = client.post("/api/projects/wizard", json=intake)
    pid = r.json()["id"]

    import term_expansion
    seen = {}

    def fake_suggest(cfg, term, **kw):
        seen["term"] = term
        return {"variants": ["diet cola"], "brands": ["Fizzly"], "translations": {},
                "term": term, "_summary": {"variants": 1, "brands": 1, "translations": 0}}

    monkeypatch.setattr(term_expansion, "suggest_terms", fake_suggest)
    r2 = client.post(f"/api/projects/{pid}/suggest-terms", json={})
    assert r2.status_code == 200
    assert seen["term"] == "cola"
    assert r2.json()["variants"] == ["diet cola"]


def test_apply_terms_creates_feeds_and_updates_competitors(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    intake = _intake()
    intake["product"] = {"brand": "", "category": "coffee", "category_type": "fmcg_food"}
    r = client.post("/api/projects/wizard", json=intake)
    pid = r.json()["id"]

    body = {
        "term": "coffee",
        "variants": ["instant coffee", "latte"],
        "brands": ["Starbucks"],
        "translations": {},
    }
    r2 = client.post(f"/api/projects/{pid}/apply-terms", json=body)
    assert r2.status_code == 200
    assert r2.json()["google_news_feeds"] == 4  # coffee + instant coffee + latte + Starbucks

    r3 = client.get(f"/api/projects/{pid}")
    assert "Starbucks" in r3.json()["config"]["competitors"]


def test_apply_terms_rejects_empty_term(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    r = client.post("/api/projects/wizard", json=_intake())
    pid = r.json()["id"]
    r2 = client.post(f"/api/projects/{pid}/apply-terms", json={"term": "", "variants": ["x"]})
    assert r2.status_code == 400


def test_suggest_outlets_calls_discovery_module(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    r = client.post("/api/projects/wizard", json=_intake())
    pid = r.json()["id"]

    import outlet_discovery

    def fake_suggest(cfg, **kw):
        return {"outlets": [{"name": "Scroll.in", "domain": "scroll.in", "category": "news",
                             "language": "en", "why": "x", "caution": False}],
                "_summary": {"total": 1, "caution": 0, "by_category": {"news": 1}}}

    monkeypatch.setattr(outlet_discovery, "suggest_outlets", fake_suggest)
    r2 = client.post(f"/api/projects/{pid}/suggest-outlets")
    assert r2.status_code == 200
    assert r2.json()["outlets"][0]["name"] == "Scroll.in"


def test_apply_outlets_adds_to_market_terms(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    r = client.post("/api/projects/wizard", json=_intake())
    pid = r.json()["id"]
    before = len(r.json()["config"]["market"]["market_terms"])

    r2 = client.post(f"/api/projects/{pid}/apply-outlets", json={"names": ["Scroll.in", "NDTV"]})
    assert r2.status_code == 200
    assert r2.json()["market_terms_count"] == before + 2

    r3 = client.get(f"/api/projects/{pid}")
    assert "Scroll.in" in r3.json()["config"]["market"]["market_terms"]
    assert "NDTV" in r3.json()["config"]["market"]["market_terms"]


def test_health_reports_key_presence_not_values(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    import settings as settings_mod
    monkeypatch.setattr(settings_mod.settings, "anthropic_api_key", "sk-secret-value")
    monkeypatch.setattr(settings_mod.settings, "youtube_api_key", "")
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    # Booleans only — the actual secret value is never exposed.
    assert body["keys"]["anthropic"] is True
    assert body["keys"]["youtube"] is False
    assert "sk-secret-value" not in r.text
    assert "deps" in body


def test_health_requires_auth_in_team_mode(client, monkeypatch):
    monkeypatch.setenv("MODE", "team")
    assert client.get("/api/health").status_code == 401


def test_collect_extensive_enqueues_full_year_per_channel(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    pid = storage.create_project("P", {"source_plan": {}, "market": {"country": "Malaysia"}})
    captured = []
    monkeypatch.setattr("jobs.enqueue",
                        lambda p, ch, params, triggered_by=None: (captured.append((ch, params)) or len(captured)))
    r = client.post(f"/api/projects/{pid}/collect-extensive",
                    json={"channels": ["news", "gdelt", "reddit"], "year": 2026, "market_only": True})
    assert r.status_code == 200
    body = r.json()
    assert [j["channel"] for j in body["jobs"]] == ["news", "gdelt", "reddit"]
    # Each channel enqueued with full-year monthly-chunked params.
    chans = {c for c, _ in captured}
    assert chans == {"news", "gdelt", "reddit"}
    for _, params in captured:
        assert params["chunk"] == "monthly"
        assert params["start_date"] == "2026-01-01" and params["end_date"] == "2026-12-31"
        assert params["market_only"] is True


def test_purge_requires_confirmation(client, monkeypatch):
    monkeypatch.setenv("MODE", "solo")
    pid = storage.create_project("P", {"source_plan": {}})
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 400
    r = client.delete(f"/api/projects/{pid}?confirm=DELETE")
    assert r.status_code == 200
    assert storage.get_project(pid) is None
