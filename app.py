"""MarketLens FastAPI application — routes + static SPA + startup wiring.

Run: ``python app.py`` (solo, 127.0.0.1) or ``MODE=team python app.py`` (team, 0.0.0.0,
login required). Also boots via ``docker compose up``.
"""
from __future__ import annotations

import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import analysis
import analytics
import archive
import auth
import config as config_mod
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
@app.get("/api/projects")
def api_projects(user: str = Depends(require_user)):
    return storage.list_projects()


@app.post("/api/projects/wizard")
def api_wizard(intake: Dict[str, Any], user: str = Depends(require_user)):
    cfg = config_mod.run_wizard(intake)
    name = intake.get("name") or cfg["product"]["brand"] or "Untitled study"
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
    }
    if name not in fns:
        raise HTTPException(status_code=404, detail=f"unknown aggregate: {name}")
    return fns[name]()


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
                                     published_before=body.get("published_before"))
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
    """Download the report draft as Markdown (fmt=md) or Word (fmt=docx)."""
    _project_or_404(pid)
    try:
        if fmt == "docx":
            path = report_mod.save_docx(pid)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            path = report_mod.save_markdown(pid)
            media = "text/markdown"
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=501, detail=f"{e}. Install requirements: pip install python-docx")
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


def main():
    import uvicorn

    uvicorn.run("app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
