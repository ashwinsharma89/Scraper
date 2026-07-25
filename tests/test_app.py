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
