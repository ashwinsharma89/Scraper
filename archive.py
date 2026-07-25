"""Project export / import as a single portable archive.

A project's config + items + analysis + market intel + run log (and any uploaded
screenshots) export to one ``.mlz`` zip and import cleanly onto another instance — a
study can move between a laptop and a team server. The Excel export is the client-facing
artifact; this archive is the working-data transfer format.

Round-trips losslessly: content hashes, run lineage (remapped to new ids), and analysis
tags all survive an export->import onto a fresh DB.
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import storage
from settings import settings
from version import __version__

ARCHIVE_SCHEMA = 1
MANIFEST_NAME = "manifest.json"


def export_project(project_id: int, out_path: Optional[str] = None) -> str:
    project = storage.get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")

    with storage.get_conn() as conn:
        runs = [dict(r) for r in conn.execute(
            "SELECT id, channel, params_json, status, started_at, finished_at, rows_returned, "
            "rows_new, rows_duplicate, errors_json, triggered_by FROM runs WHERE project_id=? ORDER BY id",
            (project_id,)).fetchall()]
        items = [dict(r) for r in conn.execute(
            "SELECT id, run_id, source, content_hash, title, text, link, published, extra_json, "
            "created_at FROM items WHERE project_id=? ORDER BY id", (project_id,)).fetchall()]
        analysis = [dict(r) for r in conn.execute(
            "SELECT item_id, model, sentiment, sentiment_score, language, summary_en, rating_signal, "
            "purchase_driver, usage_occasion, trend_category, brand_focus, promo_mentioned, emotion, "
            "raw_json, created_at FROM analysis WHERE project_id=? ORDER BY item_id",
            (project_id,)).fetchall()]
        intel = [dict(r) for r in conn.execute(
            "SELECT entry_type, category, metric, value, source_name, source_url, publication_date, "
            "accessed_date, confidence, notes, extra_json, entered_by, created_at, updated_at "
            "FROM market_intel WHERE project_id=? ORDER BY id", (project_id,)).fetchall()]

    manifest = {
        "marketlens_archive_schema": ARCHIVE_SCHEMA,
        "tool_version": __version__,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": {"name": project["name"], "config": project["config"]},
        "runs": runs, "items": items, "analysis": analysis, "market_intel": intel,
    }

    settings.ensure_dirs()
    if out_path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = "".join(c for c in project["name"] if c.isalnum() or c in "-_") or "project"
        out_path = str(settings.archives_dir / f"{safe}_{ts}.mlz")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        # Bundle referenced screenshot attachments if present.
        for e in intel:
            extra = json.loads(e.get("extra_json") or "{}")
            sp = extra.get("screenshot_path")
            if sp and Path(sp).exists():
                zf.write(sp, arcname=f"attachments/{Path(sp).name}")

    storage.audit("archive.export", f"exported project {project_id} -> {Path(out_path).name}",
                  project_id=project_id)
    return out_path


def import_project(archive_path: str, new_name: Optional[str] = None,
                   acting_user: Optional[str] = None) -> int:
    with zipfile.ZipFile(archive_path, "r") as zf:
        manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        # Extract attachments into uploads dir.
        settings.ensure_dirs()
        for name in zf.namelist():
            if name.startswith("attachments/") and not name.endswith("/"):
                target = settings.uploads_dir / Path(name).name
                target.write_bytes(zf.read(name))

    proj = manifest["project"]
    name = new_name or proj["name"]
    new_pid = storage.create_project(name, proj["config"])

    run_map: Dict[int, int] = {}
    item_map: Dict[int, int] = {}

    with storage.write_conn() as conn:
        for run in manifest.get("runs", []):
            cur = conn.execute(
                "INSERT INTO runs (project_id, channel, params_json, status, started_at, finished_at, "
                "rows_returned, rows_new, rows_duplicate, errors_json, triggered_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (new_pid, run["channel"], run["params_json"], run["status"], run["started_at"],
                 run["finished_at"], run["rows_returned"], run["rows_new"], run["rows_duplicate"],
                 run["errors_json"], run["triggered_by"]))
            run_map[run["id"]] = int(cur.lastrowid)

        for it in manifest.get("items", []):
            new_run = run_map.get(it["run_id"])
            cur = conn.execute(
                "INSERT INTO items (project_id, run_id, source, content_hash, title, text, link, "
                "published, extra_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_pid, new_run, it["source"], it["content_hash"], it["title"], it["text"],
                 it["link"], it["published"], it["extra_json"], it["created_at"]))
            item_map[it["id"]] = int(cur.lastrowid)

        for a in manifest.get("analysis", []):
            new_item = item_map.get(a["item_id"])
            if new_item is None:
                continue
            conn.execute(
                "INSERT INTO analysis (item_id, project_id, model, sentiment, sentiment_score, language, "
                "summary_en, rating_signal, purchase_driver, usage_occasion, trend_category, brand_focus, "
                "promo_mentioned, emotion, raw_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_item, new_pid, a["model"], a["sentiment"], a["sentiment_score"], a["language"],
                 a["summary_en"], a["rating_signal"], a["purchase_driver"], a["usage_occasion"],
                 a["trend_category"], a["brand_focus"], a["promo_mentioned"], a["emotion"],
                 a["raw_json"], a["created_at"]))

        for e in manifest.get("market_intel", []):
            conn.execute(
                "INSERT INTO market_intel (project_id, entry_type, category, metric, value, source_name, "
                "source_url, publication_date, accessed_date, confidence, notes, extra_json, entered_by, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_pid, e["entry_type"], e["category"], e["metric"], e["value"], e["source_name"],
                 e["source_url"], e["publication_date"], e["accessed_date"], e["confidence"], e["notes"],
                 e["extra_json"], e["entered_by"], e["created_at"], e["updated_at"]))

    storage.audit("archive.import", f"imported '{name}' from {Path(archive_path).name}",
                  acting_user=acting_user, project_id=new_pid)
    return new_pid
