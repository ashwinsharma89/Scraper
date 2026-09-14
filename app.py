"""MarketLens FastAPI application — routes + static SPA + startup wiring.

Run: ``python app.py`` (solo, 127.0.0.1) or ``MODE=team python app.py`` (team, 0.0.0.0,
login required). Also boots via ``docker compose up``.
"""
from __future__ import annotations

import io
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import analysis
import analytics
import archive
import auth
import config as config_mod
import discovery_pipeline
import export as export_mod
import jobs
import market_intel
import report as report_mod
import scheduler
import storage
from settings import settings
from version import __version__

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    storage.init_db()
    msg = auth.bootstrap_admin()
    if msg:
        print(msg)
    print(f"MarketLens v{__version__} starting in {settings.mode.upper()} mode on "
          f"{settings.host}:{settings.port}")
    if settings.mode != "test":
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="MarketLens", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    """This is a no-build-step vanilla-JS SPA under active iteration — a browser silently
    serving a stale cached copy of static/app.js or index.html after a code change (no
    error, just old behavior/an empty dropdown/etc.) is a real, confusing failure mode
    with zero explicit Cache-Control otherwise. Static assets are small and local; the
    cost of never caching them is negligible next to that confusion."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------------------------------- #
# Auth dependency
# --------------------------------------------------------------------------- #
def require_user(request: Request) -> str:
    """Return acting user; in team mode a missing/invalid session -> 401."""
    user = auth.current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required (team mode).")
    return user


def _project_or_404(pid: int) -> Dict[str, Any]:
    p = storage.get_project(pid)
    if not p:
        raise HTTPException(status_code=404, detail=f"Project {pid} not found")
    return p


# --------------------------------------------------------------------------- #
# Meta / auth
# --------------------------------------------------------------------------- #
@app.get("/api/version")
def api_version():
    return {"version": __version__, "mode": settings.mode}


@app.get("/api/mode")
def api_mode(request: Request):
    user = auth.current_user(request)
    return {"mode": settings.mode, "team": settings.is_team, "authenticated": user is not None,
            "user": user}


@app.get("/api/health")
def api_health(request: Request):
    """Report which API keys are DETECTED (boolean only — never the value) + optional deps.

    Powers the UI's key-status indicators so a user can verify config at a glance.
    """
    # In team mode only surface this to an authenticated user.
    if settings.is_team and auth.current_user(request) is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    def _installed(mod: str) -> bool:
        import importlib.util
        return importlib.util.find_spec(mod) is not None

    return {
        "version": __version__,
        "mode": settings.mode,
        "keys": {
            "anthropic": bool(settings.anthropic_api_key),
            "youtube": bool(settings.youtube_api_key),
            "google_places": bool(settings.places_api_key),
            "twitter": bool(settings.twitter_api_key),
        },
        "deps": {
            "playwright": _installed("playwright"),
            "pytrends": _installed("pytrends"),
            "pillow": _installed("PIL"),
            "anthropic_sdk": _installed("anthropic"),
        },
    }


@app.post("/api/auth/login")
async def api_login(request: Request, response: Response):
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    if not auth.authenticate(username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = auth.make_session_token(username)
    resp = JSONResponse({"ok": True, "user": username})
    resp.set_cookie(auth.SESSION_COOKIE, token, httponly=True, samesite="lax",
                    secure=False, max_age=7 * 24 * 3600)
    return resp


@app.post("/api/auth/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


@app.post("/api/auth/users")
def api_create_user(request: Request, body: Dict[str, Any], user: str = Depends(require_user)):
    # Only an admin may create users in team mode.
    acting = storage.get_user(user)
    if settings.is_team and (not acting or not acting["is_admin"]):
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        uid = auth.create_user(body["username"], body["password"], bool(body.get("is_admin")))
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": uid, "username": body["username"]}


# --------------------------------------------------------------------------- #
# Projects + wizard
# --------------------------------------------------------------------------- #
@app.get("/api/reference/languages")
def api_reference_languages(user: str = Depends(require_user)):
    """Backs the intake wizard's language picker (single- and multi-select)."""
    return config_mod.list_languages()


@app.get("/api/reference/countries")
def api_reference_countries(user: str = Depends(require_user)):
    """Backs the intake wizard's country/region picker (single- and multi-select control;
    a study itself still targets one market — enforced in api_wizard below)."""
    return config_mod.list_countries()


@app.get("/api/projects")
def api_projects(user: str = Depends(require_user)):
    return storage.list_projects()


# --------------------------------------------------------------------------- #
# Category-aware discovery (DESIGN_01_category-discovery.md, Phase B increment 1)
#
# Pre-project, stateless wizard-support endpoints — the new wizard accumulates a draft
# intake client-side and calls these one step at a time; nothing is persisted as a real
# project until the existing /api/projects/wizard is finally called (DESIGN_01 §12).
# --------------------------------------------------------------------------- #
@app.post("/api/discovery/classify-category")
def api_classify_category(body: Dict[str, Any], user: str = Depends(require_user)):
    term = (body or {}).get("term", "")
    geo_scope = (body or {}).get("geo_scope")
    import category_discovery
    try:
        return category_discovery.classify_category(term, geo_scope=geo_scope)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/discovery/sites")
def api_discover_sites(body: Dict[str, Any], user: str = Depends(require_user)):
    """AI-suggest real sites for a category, merged with the cross-project site
    intelligence ledger (DESIGN_01 §4b) — sites with a real, good track record are shown
    pre-trusted; everything else is flagged for manual validation. Read-only.

    Optional `source_type_hint` (e.g. "lifestyle & food blogs", "forums") scopes the
    search to one genre — the wizard calls this once per confirmed source type instead
    of one blended call, so specialist/smaller sites aren't crowded out by mainstream
    news (real feedback: a single generic call kept surfacing the same handful of big
    outlets rather than food blogs or forums)."""
    category = (body or {}).get("category", "")
    geo_scope = (body or {}).get("geo_scope")
    source_type_hint = (body or {}).get("source_type_hint")
    import site_intelligence
    try:
        return site_intelligence.discover_sites(category, geo_scope=geo_scope,
                                                source_type_hint=source_type_hint)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/discovery/similar-sites")
def api_similar_sites(body: Dict[str, Any], user: str = Depends(require_user)):
    """"Sites like X" — asked for explicitly: confirming interest in one real site (e.g.
    hindustantimes.com) should surface more of the same genre (toi.com, indianexpress.com,
    ...) without re-running the whole category search. Read-only, same contract as
    /api/discovery/sites."""
    body = body or {}
    seed_domain = body.get("domain", "")
    category = body.get("category", "")
    geo_scope = body.get("geo_scope")
    import site_intelligence
    try:
        return site_intelligence.find_similar_sites(seed_domain, category, geo_scope=geo_scope)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/discovery/confirm-sites")
def api_confirm_sites(body: Dict[str, Any], user: str = Depends(require_user)):
    """User-confirmed subset of /api/discovery/sites' output — the only place anything is
    written to the site intelligence ledger from the discovery step itself."""
    category = (body or {}).get("category", "")
    domains = (body or {}).get("domains") or []
    import site_intelligence
    try:
        return site_intelligence.confirm_sites(category, domains)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/discovery/suggest-languages")
def api_suggest_languages(body: Dict[str, Any], user: str = Depends(require_user)):
    category = (body or {}).get("category", "")
    geo_scope = (body or {}).get("geo_scope")
    import language_suggestion
    try:
        return language_suggestion.suggest_languages(category, geo_scope=geo_scope)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/discovery/suggest-source-types")
def api_suggest_source_types(body: Dict[str, Any], user: str = Depends(require_user)):
    category = (body or {}).get("category", "")
    geo_scope = (body or {}).get("geo_scope")
    import source_type_mapping
    try:
        return source_type_mapping.suggest_source_types(category, geo_scope=geo_scope)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/discovery/suggest-terms-draft")
def api_suggest_terms_draft(body: Dict[str, Any], user: str = Depends(require_user)):
    """Same as /api/projects/{pid}/suggest-terms (term_expansion.suggest_terms), but takes
    a raw draft config instead of a project id — the new wizard has no project yet at this
    step (DESIGN_01 §12: "each step is a client-side wizard state ... until the final step")."""
    body = body or {}
    cfg = body.get("cfg") or {}
    term = (body.get("term") or "").strip() or cfg.get("product", {}).get("category", "")
    import term_expansion
    try:
        return term_expansion.suggest_terms(cfg, term)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/discovery/launch-study")
def api_launch_study(body: Dict[str, Any], user: str = Depends(require_user)):
    """Wizard step j (Review & launch): creates the real project via the existing,
    unchanged /api/projects/wizard validation (reused directly, not duplicated), then —
    for any confirmed generic-site-discovery domains — starts a real, resumable
    background job (Increment 6's run_source_type_job) via storage.start_run() +
    a daemon thread, returning the run_id immediately so the client can poll the
    existing GET /api/projects/{pid}/runs for status instead of a new endpoint.
    """
    body = body or {}
    intake = body.get("intake") or {}
    generic_domains: List[str] = [d for d in (body.get("generic_site_domains") or []) if d]
    keywords = body.get("keywords") or []
    volume_cap = int(body.get("volume_cap") or discovery_pipeline.DEFAULT_PER_SOURCE_CAP)
    run_daily = bool(body.get("run_daily"))
    term_exp = body.get("term_expansion") or {}  # {term, variants, brands, translations}

    project = api_wizard(intake, user)  # reuses all existing wizard validation unchanged
    pid = project["id"]
    cfg = project["config"]

    # Apply the wizard step e (brands/competitors) confirmation the same way the
    # existing /api/projects/{pid}/apply-terms endpoint does — reused, not duplicated:
    # each confirmed variant/brand becomes its own keyword structure, brands are added
    # to competitors, and News feeds are regenerated to include them immediately.
    if term_exp.get("variants") or term_exp.get("brands"):
        import term_expansion
        cfg = term_expansion.apply_expansion(
            cfg, (term_exp.get("term") or "").strip() or cfg.get("product", {}).get("category", ""),
            variants=term_exp.get("variants") or [], brands=term_exp.get("brands") or [],
            translations=term_exp.get("translations") or {},
        )
        cfg = config_mod.regenerate_news_feeds(cfg)
        storage.update_project_config(pid, cfg, None)

    category = cfg.get("product", {}).get("category", "")
    relevance_terms = cfg.get("relevance_terms") or ([category] if category else [])

    run_id = None
    if generic_domains and category:
        run_id = storage.start_run(
            pid, "generic_site",
            {"category": category, "seed_domains": generic_domains, "keywords": keywords},
            triggered_by=user, job_kind="backfill",
        )
        # site_intelligence is confirmed here (not earlier) so nothing is written to the
        # global cross-project ledger until the human's final launch action, matching every
        # other module's "confirm is the only write path" contract.
        import site_intelligence
        site_intelligence.confirm_sites(category, generic_domains)

        def _run_job():
            try:
                discovery_pipeline.run_source_type_job(
                    pid, category, generic_domains, keywords=keywords,
                    relevance_terms=relevance_terms, per_source_cap=volume_cap,
                    job_kind="backfill", run_id=run_id, triggered_by=user,
                )
            except Exception:
                pass  # the run row itself already records failure state; never crash the thread

        threading.Thread(target=_run_job, daemon=True, name=f"discovery-job-{run_id}").start()

    storage.audit("discovery.launch",
                  f"launched study '{project['name']}'" + (f" + generic-site job {run_id}" if run_id else ""),
                  acting_user=user, project_id=pid)
    return {"project_id": pid, "name": project["name"], "run_id": run_id,
            "run_daily_requested": run_daily}  # daily scheduling itself: not wired yet, see §9


def _validate_and_normalize_market(market: Dict[str, Any]) -> None:
    """Shared by api_wizard and api_update_settings: validates + normalizes a `market`
    dict in place (geo_scope shape, single-country guard, non-empty country). Factored
    out so editing settings post-creation enforces the exact same invariants the wizard
    does at creation time, rather than a second, driftable copy of the same checks."""
    # Optional, additive: a hierarchical geo-scope (country/state/region/city) per
    # DESIGN_01_category-discovery.md §3, superseding the single-country-only framing with a
    # variable-granularity one. Absent geo_scope -> behavior is IDENTICAL to before this was
    # added (existing callers/tests are unaffected). Present geo_scope derives market.country
    # so every existing country-level lookup (config.COUNTRY_TABLE: ISO/GDELT/demonym/
    # native_names) keeps working unchanged regardless of the chosen granularity — a city
    # still needs its parent country's facts.
    geo_scope = market.get("geo_scope")
    if geo_scope is not None:
        if not isinstance(geo_scope, dict):
            raise HTTPException(status_code=400,
                                 detail="geo_scope must be an object with level/value/country.")
        level = (geo_scope.get("level") or "").strip().lower()
        value = (geo_scope.get("value") or "").strip()
        geo_country = (geo_scope.get("country") or "").strip()
        if level not in config_mod.GEO_SCOPE_LEVELS:
            raise HTTPException(status_code=400,
                                 detail=f"geo_scope.level must be one of {sorted(config_mod.GEO_SCOPE_LEVELS)}.")
        if not value:
            raise HTTPException(status_code=400, detail="geo_scope.value is required.")
        if level == "country":
            geo_country = geo_country or value  # the value IS the country at this level
        if not geo_country:
            raise HTTPException(status_code=400,
                                 detail="geo_scope.country is required for state/region/city scopes.")
        market["geo_scope"] = {"level": level, "value": value, "country": geo_country}
        market["country"] = geo_country

    # A study targets exactly one market. The intake form's country control allows
    # multi-select (same widget as languages, for interaction consistency), but a study's
    # country field itself is a single string throughout config.py/GDELT/Google News/etc —
    # so more than one value here means the form's own guard was bypassed (e.g. a direct
    # API call). Reject rather than silently pick one.
    country_val = market.get("country")
    if isinstance(country_val, list):
        if len(country_val) != 1:
            raise HTTPException(status_code=400,
                                 detail="A study targets exactly one country/region.")
        market["country"] = country_val[0]
    if not (market.get("country") or "").strip():
        raise HTTPException(status_code=400, detail="Country/region is required.")


@app.post("/api/projects/wizard")
def api_wizard(intake: Dict[str, Any], user: str = Depends(require_user)):
    # A study needs at least one anchor to generate keywords/relevance terms from — brand
    # OR category — but neither is hard-required on its own. This is what lets a
    # category-only study (e.g. "instant noodles in Malaysia", no single target brand) work.
    product = intake.get("product", {}) or {}
    if not (product.get("brand") or "").strip() and not (product.get("category") or "").strip():
        raise HTTPException(status_code=400,
                             detail="Provide a brand name, a product category, or both.")
    market = intake.get("market") or {}
    intake["market"] = market
    _validate_and_normalize_market(market)
    cfg = config_mod.run_wizard(intake)
    name = intake.get("name") or cfg["product"]["brand"] or cfg["product"]["category"] or "Untitled study"
    pid = storage.create_project(name, cfg)
    storage.audit("project.create", name, acting_user=user, project_id=pid)
    return {"id": pid, "name": name, "config": cfg}


@app.get("/api/projects/{pid}")
def api_get_project(pid: int, user: str = Depends(require_user)):
    return _project_or_404(pid)


@app.put("/api/projects/{pid}/config")
def api_update_config(pid: int, body: Dict[str, Any], user: str = Depends(require_user)):
    _project_or_404(pid)
    cfg = body.get("config")
    name = body.get("name")
    storage.update_project_config(pid, cfg, name)
    storage.audit("project.update", "config edited", acting_user=user, project_id=pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/update-settings")
def api_update_settings(pid: int, body: Dict[str, Any], user: str = Depends(require_user)):
    """Change a study's market/brand/competitors after creation and regenerate the
    market/product-dependent parts of the source plan in place (HANDOFF §7 item 3:
    "today the market is only set at wizard time"). Every user-filled source_plan URL
    list and every existing language's keyword structures are preserved untouched —
    see config.update_settings()'s docstring for exactly what is/isn't recomputed."""
    project = _project_or_404(pid)
    body = body or {}
    product = body.get("product") or {}
    if not (product.get("brand") or "").strip() and not (product.get("category") or "").strip():
        raise HTTPException(status_code=400,
                             detail="Provide a brand name, a product category, or both.")
    market = body.get("market") or {}
    _validate_and_normalize_market(market)
    competitors = [c for c in (body.get("competitors") or []) if c]

    new_cfg = config_mod.update_settings(project["config"], market, product, competitors)
    name = body.get("name") or project["name"]
    storage.update_project_config(pid, new_cfg, name)
    storage.audit("project.update", "settings edited (market/brand/competitors)",
                 acting_user=user, project_id=pid)
    return {
        "ok": True,
        "config": new_cfg,
        "google_news_feeds": len(new_cfg["source_plan"]["google_news_feeds"]),
        "bing_news_feeds": len(new_cfg["source_plan"]["bing_news_feeds"]),
    }


@app.post("/api/projects/{pid}/regenerate-feeds")
def api_regenerate_feeds(pid: int, user: str = Depends(require_user)):
    """Recompute Google/Bing News feeds from the project's current keyword slots. Needed
    because PUT .../config just stores whatever JSON it's given — editing keywords in
    Source Plan does not, on its own, update the feed list the News scraper actually
    reads at collect time. Call this after editing keyword slots."""
    project = _project_or_404(pid)
    new_cfg = config_mod.regenerate_news_feeds(project["config"])
    storage.update_project_config(pid, new_cfg, None)
    storage.audit("project.update", "regenerated news feeds from keywords", acting_user=user, project_id=pid)
    return {
        "ok": True,
        "google_news_feeds": len(new_cfg["source_plan"]["google_news_feeds"]),
        "bing_news_feeds": len(new_cfg["source_plan"]["bing_news_feeds"]),
    }


@app.delete("/api/projects/{pid}")
def api_delete_project(pid: int, confirm: str = "", user: str = Depends(require_user)):
    _project_or_404(pid)
    if confirm != "DELETE":
        raise HTTPException(status_code=400, detail="Purge requires confirm=DELETE")
    storage.audit("project.purge", "explicit confirmed purge", acting_user=user, project_id=pid)
    storage.delete_project(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/config.yaml")
def api_config_yaml(pid: int, user: str = Depends(require_user)):
    p = _project_or_404(pid)
    text = yaml.safe_dump(p["config"], allow_unicode=True, sort_keys=False)
    return PlainTextResponse(text, media_type="application/x-yaml")


@app.post("/api/projects/{pid}/suggest-sources")
def api_suggest_sources(pid: int, user: str = Depends(require_user)):
    """AI-suggest candidate sources for this project's market+category, then validate them.

    Returns candidates per channel with a validation status; the user confirms which to
    add. Nothing is written to the source plan here.
    """
    p = _project_or_404(pid)
    import source_discovery
    try:
        result = source_discovery.suggest_sources(p["config"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage.audit("sources.suggest", "AI source discovery run", acting_user=user, project_id=pid)
    return result


@app.post("/api/projects/{pid}/suggest-terms")
def api_suggest_terms(pid: int, body: Dict[str, Any], user: str = Depends(require_user)):
    """AI-expand a narrow search term into product variants, real brand/shop names, and
    per-language translations (e.g. "coffee" -> instant coffee, cold coffee, latte,
    Starbucks, Costa Coffee, + native-script equivalents in the study's other languages).

    Returns candidates only — nothing is written to keyword structures here; the user
    confirms which to add via /apply-terms.
    """
    p = _project_or_404(pid)
    term = (body or {}).get("term") or p["config"].get("product", {}).get("category", "")
    import term_expansion
    try:
        result = term_expansion.suggest_terms(p["config"], term)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage.audit("terms.suggest", f"AI term expansion for '{term}'", acting_user=user, project_id=pid)
    return result


@app.post("/api/projects/{pid}/apply-terms")
def api_apply_terms(pid: int, body: Dict[str, Any], user: str = Depends(require_user)):
    """Apply a user-CONFIRMED subset of /suggest-terms' output: each selected variant/
    brand/translation becomes its own keyword structure (own News feed), brands are added
    to competitors, and Google/Bing News feeds are regenerated to reflect it immediately.
    """
    p = _project_or_404(pid)
    body = body or {}
    term = (body.get("term") or "").strip()
    if not term:
        raise HTTPException(status_code=400, detail="term is required")
    import term_expansion
    new_cfg = term_expansion.apply_expansion(
        p["config"], term,
        variants=body.get("variants") or [],
        brands=body.get("brands") or [],
        translations=body.get("translations") or {},
    )
    new_cfg = config_mod.regenerate_news_feeds(new_cfg)
    storage.update_project_config(pid, new_cfg, None)
    storage.audit("terms.apply", f"Applied term expansion for '{term}'", acting_user=user, project_id=pid)
    return {
        "ok": True,
        "google_news_feeds": len(new_cfg["source_plan"]["google_news_feeds"]),
        "bing_news_feeds": len(new_cfg["source_plan"]["bing_news_feeds"]),
    }


@app.post("/api/projects/{pid}/suggest-outlets")
def api_suggest_outlets(pid: int, user: str = Depends(require_user)):
    """AI-suggest real local outlets (news, lifestyle, business, tech, sports, regional —
    not just hard news) for this project's market+languages, so the market-relevance gate
    can recognize them even though most don't carry the country's name in their own brand.

    Returns candidates only — nothing is written until confirmed via /apply-outlets.
    """
    p = _project_or_404(pid)
    import outlet_discovery
    try:
        result = outlet_discovery.suggest_outlets(p["config"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage.audit("outlets.suggest", "AI local-outlet discovery run", acting_user=user, project_id=pid)
    return result


@app.post("/api/projects/{pid}/apply-outlets")
def api_apply_outlets(pid: int, body: Dict[str, Any], user: str = Depends(require_user)):
    """Apply a user-CONFIRMED subset of /suggest-outlets' OR /suggest-market-terms'
    output: each selected name is added to market.market_terms so the news market gate
    recognizes it as in-market on its own. No feed regeneration needed — this only
    affects relevance filtering. Shared by both suggestion features (outlets and city/
    region terms both just append strings to the same field, with the same dedup
    semantics) rather than duplicating an apply endpoint per suggestion source; `kind`
    only changes the audit-log wording, never behavior."""
    p = _project_or_404(pid)
    body = body or {}
    names = body.get("names") or []
    kind = body.get("kind") or "local outlet"
    import outlet_discovery
    new_cfg = outlet_discovery.apply_outlets(p["config"], names)
    storage.update_project_config(pid, new_cfg, None)
    storage.audit("outlets.apply", f"Added {len(names)} {kind}(s) to market terms",
                  acting_user=user, project_id=pid)
    return {"ok": True, "market_terms_count": len(new_cfg["market"]["market_terms"])}


@app.post("/api/projects/{pid}/suggest-market-terms")
def api_suggest_market_terms(pid: int, user: str = Depends(require_user)):
    """AI-suggest real, category-relevant cities/regions within this project's market
    (HANDOFF §7: "Auto-suggest city/region market terms to further reduce market-filter
    over-drop") — the same demonym-style gap one geographic level down: an article
    naming only "Lagos", never "Nigeria," is in-market but undetected without this.

    Returns candidates only — nothing is written until confirmed via /apply-outlets
    (same target field as outlet suggestions, so it's reused rather than duplicated)."""
    p = _project_or_404(pid)
    import geo_term_discovery
    try:
        result = geo_term_discovery.suggest_market_terms(p["config"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage.audit("market_terms.suggest", "AI city/region market-term discovery run",
                  acting_user=user, project_id=pid)
    return result


def _project_geo_scope(cfg: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """market.geo_scope when the project has one (set via the AI-guided wizard's
    geo-scope step); otherwise a synthetic country-level scope from market.country,
    since every project has AT LEAST a country even when created through the plain
    wizard (which never collects a geo_scope at all)."""
    market = cfg.get("market", {})
    if market.get("geo_scope"):
        return market["geo_scope"]
    country = market.get("country", "")
    return {"level": "country", "value": country, "country": country} if country else None


@app.post("/api/projects/{pid}/suggest-source-types")
def api_suggest_source_types_for_project(pid: int, user: str = Depends(require_user)):
    """HANDOFF §7 item 4 retrofit: the category-discovery pipeline (real source TYPES
    like "café/venue listing sites"/"coffee brand blogs", then real sitemap-based site
    discovery for each — source_type_mapping.py + site_intelligence.py +
    discovery_pipeline.py) previously only ran once, at creation time, through the
    AI-guided study wizard. This lets an EXISTING project run it too — real user report:
    "why doesn't it search India's top food/lifestyle sites, cafes, coffee brands" for a
    study that was created through the plain wizard, which never touches this pipeline
    at all. Layer 1 only; nothing is written here — see /discover-sites-for-type and
    the existing generic /api/discovery/confirm-sites for the write path."""
    p = _project_or_404(pid)
    cfg = p["config"]
    category = cfg.get("product", {}).get("category", "")
    if not category:
        raise HTTPException(status_code=400, detail="This project has no category set.")
    import source_type_mapping
    try:
        result = source_type_mapping.suggest_source_types(category, geo_scope=_project_geo_scope(cfg))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage.audit("source_types.suggest", "AI source-type discovery run", acting_user=user, project_id=pid)
    return result


@app.post("/api/projects/{pid}/discover-sites-for-type")
def api_discover_sites_for_project(pid: int, body: Dict[str, Any], user: str = Depends(require_user)):
    """Layer 2a for an existing project: real candidate sites for ONE confirmed source
    type (source_type_hint), merged with the cross-project site-intelligence ledger —
    same contract as /api/discovery/sites (called once per genre, not blended, for the
    same reason the wizard does: a single call keeps surfacing the same mainstream
    outlets over specialist/smaller sites). Read-only; nothing written until confirmed
    via /api/discovery/confirm-sites."""
    p = _project_or_404(pid)
    cfg = p["config"]
    category = cfg.get("product", {}).get("category", "")
    source_type_hint = (body or {}).get("source_type_hint")
    if not category:
        raise HTTPException(status_code=400, detail="This project has no category set.")
    import site_intelligence
    try:
        result = site_intelligence.discover_sites(category, geo_scope=_project_geo_scope(cfg),
                                                   source_type_hint=source_type_hint)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage.audit("sites.discover", f"AI site discovery for '{source_type_hint or category}'",
                  acting_user=user, project_id=pid)
    return result


@app.post("/api/projects/{pid}/feed-health")
def api_feed_health(pid: int, body: Dict[str, Any] = None, user: str = Depends(require_user)):
    p = _project_or_404(pid)
    urls = (body or {}).get("urls")
    if urls is None:
        urls = p["config"].get("source_plan", {}).get("rss_feeds", [])
    return {"results": config_mod.feed_health_check(urls)}


# --------------------------------------------------------------------------- #
# Collection + jobs
# --------------------------------------------------------------------------- #
@app.post("/api/projects/{pid}/collect")
def api_collect(pid: int, body: Dict[str, Any], user: str = Depends(require_user)):
    _project_or_404(pid)
    channel = body.get("channel")
    if not channel:
        raise HTTPException(status_code=400, detail="channel required")
    params = body.get("params", {})
    job_id = jobs.enqueue(pid, channel, params, triggered_by=user)
    return {"job_id": job_id, "active": jobs.active_job()}


@app.post("/api/projects/{pid}/collect-extensive")
def api_collect_extensive(pid: int, body: Dict[str, Any], user: str = Depends(require_user)):
    """One-click extensive research: enqueue a full-year, monthly-chunked, market-filtered,
    deduplicated collection across the chosen channels. The user picks channels + year
    (the 'manual layer') — nothing auto-fires on study creation.
    """
    _project_or_404(pid)
    channels = [c for c in (body.get("channels") or ["news"]) if c]
    year = int(body.get("year", 2026))
    market_only = bool(body.get("market_only", True))
    base = {
        "chunk": "monthly",           # beats the ~100-results/query cap → extensive
        "fetch_bodies": False,
        "market_only": market_only,   # honored by news; ignored by channels that don't gate
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
    }
    enqueued = []
    for ch in channels:
        job_id = jobs.enqueue(pid, ch, dict(base), triggered_by=user)
        enqueued.append({"channel": ch, "job_id": job_id})
    storage.audit("collect.extensive", f"{year} full-year across {', '.join(channels)}",
                  acting_user=user, project_id=pid)
    return {"year": year, "channels": channels, "jobs": enqueued, "active": jobs.active_job()}


@app.get("/api/jobs/active")
def api_active_job(user: str = Depends(require_user)):
    return {"active": jobs.active_job()}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: int, user: str = Depends(require_user)):
    j = jobs.get_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    return j


@app.get("/api/projects/{pid}/jobs")
def api_project_jobs(pid: int, user: str = Depends(require_user)):
    return jobs.list_jobs(pid)


@app.get("/api/projects/{pid}/runs")
def api_runs(pid: int, user: str = Depends(require_user)):
    _project_or_404(pid)
    return storage.list_runs(pid)


@app.get("/api/projects/{pid}/items")
def api_items(pid: int, source: Optional[str] = None, limit: int = 200,
              user: str = Depends(require_user)):
    _project_or_404(pid)
    return storage.list_items(pid, source=source, limit=limit)


@app.get("/api/projects/{pid}/items-table")
def api_items_table(pid: int, source: Optional[str] = None, brand_focus: Optional[str] = None,
                    sentiment: Optional[str] = None, q: Optional[str] = None,
                    limit: int = 1000, user: str = Depends(require_user)):
    """Every item joined with its analysis columns, filterable — powers the Items browser."""
    _project_or_404(pid)
    rows = storage.items_with_analysis(pid, source=source)
    ql = (q or "").strip().lower()

    def _keep(r):
        if brand_focus and (r.get("brand_focus") or "") != brand_focus:
            return False
        if sentiment and (r.get("sentiment") or "") != sentiment:
            return False
        if ql:
            hay = f"{r.get('title','')} {r.get('text','')} {r.get('summary_en','')}".lower()
            if ql not in hay:
                return False
        return True

    filtered = [r for r in rows if _keep(r)]
    return {
        "total": len(rows),
        "matched": len(filtered),
        "sources": storage.count_items_by_source(pid),
        "rows": filtered[:limit],
    }


@app.get("/api/projects/{pid}/audit")
def api_audit(pid: int, user: str = Depends(require_user)):
    return storage.list_audit(pid)


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
@app.post("/api/projects/{pid}/analyze")
def api_analyze(pid: int, body: Dict[str, Any] = None, user: str = Depends(require_user)):
    _project_or_404(pid)
    body = body or {}
    mode = body.get("mode", "batch")
    try:
        if mode == "all":
            res = analysis.analyze_all(pid)
        else:
            res = analysis.analyze_batch(pid)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return res


@app.get("/api/projects/{pid}/dashboard")
def api_dashboard(pid: int, user: str = Depends(require_user)):
    _project_or_404(pid)
    return analytics.dashboard(pid)


@app.get("/api/projects/{pid}/analytics/{name}")
def api_analytics(pid: int, name: str, user: str = Depends(require_user)):
    _project_or_404(pid)
    fns = {
        "sentiment_by_channel": lambda: {"data": analytics.sentiment_by_channel(pid)},
        "sentiment_by_month": lambda: {"data": analytics.sentiment_by_month(pid)},
        "purchase_drivers": lambda: analytics.top_purchase_drivers(pid),
        "trend_volume": lambda: analytics.trend_volume_over_time(pid),
        "brand_vs_competitor": lambda: {"data": analytics.brand_vs_competitor_sentiment(pid)},
        "verbatims": lambda: analytics.top_verbatims_per_theme(pid),
        "relevance_recovery": lambda: analytics.relevance_recovery_stats(pid),
        "news_engine_split": lambda: analytics.news_engine_split(pid),
        "items_by_channel": lambda: {"data": analytics.items_by_channel(pid)},
        "items_by_domain": lambda: analytics.items_by_domain(pid),
    }
    if name not in fns:
        raise HTTPException(status_code=404, detail=f"unknown aggregate: {name}")
    return fns[name]()


@app.get("/api/projects/{pid}/source-health")
def api_source_health(pid: int, paused_only: bool = False, user: str = Depends(require_user)):
    """DESIGN_01 §7.4/§12's Access & Reliability panel — per-source consecutive-
    failure/pause state for THIS project (unlike site_intelligence below, which is
    global). Reused unchanged from storage.py; nothing new to compute here."""
    _project_or_404(pid)
    return storage.list_source_health(pid, paused_only=paused_only)


@app.get("/api/projects/{pid}/site-intelligence")
def api_project_site_intelligence(pid: int, user: str = Depends(require_user)):
    """DESIGN_01 §4b/§12 — the learning mechanism's visible result: what the GLOBAL,
    cross-project site_intelligence ledger has actually learned so far for THIS
    project's own category (real track record across every study that has ever used
    it, not just this one). Read-only; nothing is written from a dashboard view."""
    project = _project_or_404(pid)
    category = project["config"].get("product", {}).get("category", "")
    if not category:
        return {"category": "", "sites": []}
    return {"category": category, "sites": storage.list_site_intelligence(category, limit=50)}


# --------------------------------------------------------------------------- #
# Market intelligence
# --------------------------------------------------------------------------- #
@app.get("/api/projects/{pid}/market-intel")
def api_get_intel(pid: int, user: str = Depends(require_user)):
    _project_or_404(pid)
    return {"cited": market_intel.list_cited(pid), "manual_ads": market_intel.list_manual_ads(pid),
            "categories": market_intel.CITED_CATEGORIES, "confidence_levels": market_intel.CONFIDENCE_LEVELS}


@app.post("/api/projects/{pid}/market-intel")
def api_add_cited(pid: int, entry: Dict[str, Any], user: str = Depends(require_user)):
    _project_or_404(pid)
    try:
        iid = market_intel.add_cited_entry(pid, entry, entered_by=user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": iid}


@app.post("/api/projects/{pid}/manual-intel")
def api_add_manual(pid: int, entry: Dict[str, Any], user: str = Depends(require_user)):
    _project_or_404(pid)
    try:
        iid = market_intel.add_manual_ad(pid, entry, entered_by=user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": iid}


@app.delete("/api/projects/{pid}/market-intel/{intel_id}")
def api_del_intel(pid: int, intel_id: int, user: str = Depends(require_user)):
    _project_or_404(pid)
    storage.delete_market_intel(pid, intel_id)
    storage.audit("market_intel.delete", f"entry {intel_id}", acting_user=user, project_id=pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/manual-plan")
def api_manual_plan(pid: int, user: str = Depends(require_user)):
    p = _project_or_404(pid)
    return {"platforms": market_intel.manual_intelligence_plan(p["config"]),
            "tier3_gaps": p["config"].get("source_plan", {}).get("tier3_gaps", [])}


@app.post("/api/projects/{pid}/upload-screenshot")
async def api_upload_screenshot(pid: int, file: UploadFile, user: str = Depends(require_user)):
    _project_or_404(pid)
    settings.ensure_dirs()
    safe = "".join(c for c in (file.filename or "shot.png") if c.isalnum() or c in "-_.")
    dest = settings.uploads_dir / f"p{pid}_{safe}"
    dest.write_bytes(await file.read())
    return {"path": str(dest)}


# --------------------------------------------------------------------------- #
# Export + report
# --------------------------------------------------------------------------- #
@app.post("/api/projects/{pid}/export")
def api_export(pid: int, body: Dict[str, Any] = None, user: str = Depends(require_user)):
    _project_or_404(pid)
    body = body or {}
    path = export_mod.build_workbook(pid, published_after=body.get("published_after"),
                                     published_before=body.get("published_before"),
                                     exclude_unrelated=bool(body.get("exclude_unrelated", False)))
    return {"path": path, "filename": Path(path).name}


@app.get("/api/projects/{pid}/export/download")
def api_export_download(pid: int, path: str, user: str = Depends(require_user)):
    # Only allow serving files from the exports dir (no path traversal).
    p = Path(path).resolve()
    if settings.exports_dir.resolve() not in p.parents:
        raise HTTPException(status_code=400, detail="invalid path")
    if not p.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(p), filename=p.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/projects/{pid}/report/draft")
def api_report_draft(pid: int, user: str = Depends(require_user)):
    _project_or_404(pid)
    return PlainTextResponse(report_mod.draft_report(pid), media_type="text/markdown")


@app.get("/api/projects/{pid}/report/download")
def api_report_download(pid: int, fmt: str = "md", user: str = Depends(require_user)):
    """Download the report draft as Markdown (fmt=md), Word (fmt=docx), or PDF (fmt=pdf)."""
    _project_or_404(pid)
    try:
        if fmt == "docx":
            path = report_mod.save_docx(pid)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif fmt == "pdf":
            path = report_mod.save_pdf(pid)
            media = "application/pdf"
        else:
            path = report_mod.save_markdown(pid)
            media = "text/markdown"
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=501, detail=f"{e}. Install requirements: pip install -r requirements.txt")
    return FileResponse(str(path), filename=Path(path).name, media_type=media)


# --------------------------------------------------------------------------- #
# Scheduler
# --------------------------------------------------------------------------- #
@app.get("/api/projects/{pid}/schedules")
def api_get_schedules(pid: int, user: str = Depends(require_user)):
    _project_or_404(pid)
    return storage.list_schedules(pid)


@app.post("/api/projects/{pid}/schedules")
def api_add_schedule(pid: int, body: Dict[str, Any], user: str = Depends(require_user)):
    _project_or_404(pid)
    sid = scheduler.create_schedule(pid, body["channel"], body.get("params", {}),
                                    int(body["interval_seconds"]), created_by=user,
                                    first_run_in=int(body.get("first_run_in", 0)))
    return {"id": sid}


@app.post("/api/schedules/{sid}/pause")
def api_pause_schedule(sid: int, body: Dict[str, Any] = None, user: str = Depends(require_user)):
    paused = (body or {}).get("paused", True)
    scheduler.pause_schedule(sid, paused, acting_user=user)
    return {"ok": True}


@app.delete("/api/schedules/{sid}")
def api_delete_schedule(sid: int, user: str = Depends(require_user)):
    scheduler.delete_schedule(sid, acting_user=user)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Archive (portability)
# --------------------------------------------------------------------------- #
@app.post("/api/projects/{pid}/archive/export")
def api_archive_export(pid: int, user: str = Depends(require_user)):
    _project_or_404(pid)
    path = archive.export_project(pid)
    return {"path": path, "filename": Path(path).name}


@app.get("/api/projects/{pid}/archive/download")
def api_archive_download(pid: int, path: str, user: str = Depends(require_user)):
    p = Path(path).resolve()
    if settings.archives_dir.resolve() not in p.parents:
        raise HTTPException(status_code=400, detail="invalid path")
    if not p.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(p), filename=p.name, media_type="application/zip")


@app.post("/api/archive/import")
async def api_archive_import(file: UploadFile, user: str = Depends(require_user)):
    settings.ensure_dirs()
    tmp = settings.archives_dir / f"_import_{file.filename}"
    tmp.write_bytes(await file.read())
    new_pid = archive.import_project(str(tmp), acting_user=user)
    return {"project_id": new_pid}


@app.get("/api/channels")
def api_channels(user: str = Depends(require_user)):
    from scrapers import CHANNEL_INFO, available_channels
    return {"channels": available_channels(), "info": CHANNEL_INFO}


# --------------------------------------------------------------------------- #
# Static SPA
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return HTMLResponse(idx.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>MarketLens</h1><p>Static UI not found.</p>")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{full_path:path}", response_class=HTMLResponse)
def spa_fallback(full_path: str):
    """React Router client-side routing (adopted with the React rewrite) means a direct
    load or a refresh on e.g. /items must still return the SPA shell, not a 404 — the
    browser then runs React Router's own matching against that path. Real bug, found
    live: before this existed, refreshing on any tab other than "/" 404'd.

    Every real /api/* route is registered above this catch-all, so an actual API call
    always matches its own route first — this only ever fires for a GET that didn't
    match anything else. An unmatched /api/... path still 404s explicitly here rather
    than silently returning the HTML shell, which would hide a genuine backend error
    (e.g. a typo'd endpoint) behind a confusing 200.
    """
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return HTMLResponse(idx.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>MarketLens</h1><p>Static UI not found.</p>", status_code=404)


def main():
    import uvicorn

    uvicorn.run("app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
