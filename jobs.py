"""Single-writer job queue + the collection runner.

Concurrency safety: all scrape jobs run through ONE worker thread, so two users (or a
user + the scheduler) triggering scrapes can never corrupt state or interleave writes.
User B sees User A's running job via the job-status endpoint instead of a frozen button.

The runner is the single place that wraps a scraper's pure ``collect()`` with
start_run / save_items / finish_run, so lineage + dedup are enforced identically for
every channel and every trigger (manual, scheduled, or API).
"""
from __future__ import annotations

import itertools
import threading
import time
import traceback
from datetime import datetime, timezone
from queue import Queue
from typing import Any, Callable, Dict, List, Optional

import storage
from scrapers import get_scraper

_job_counter = itertools.count(1)
_jobs: Dict[int, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_queue: "Queue[int]" = Queue()
_worker_started = False
_worker_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, name="marketlens-jobs", daemon=True)
        t.start()
        _worker_started = True


def _worker_loop() -> None:
    while True:
        job_id = _queue.get()
        try:
            _execute(job_id)
        except Exception:  # never let the worker thread die
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job:
                    job["status"] = "error"
                    job["error"] = traceback.format_exc()
                    job["finished_at"] = _now()
        finally:
            _queue.task_done()


def enqueue(project_id: int, channel: str, params: Optional[Dict[str, Any]] = None,
            triggered_by: Optional[str] = None) -> int:
    """Queue a collection job. Returns a job id for status polling."""
    _ensure_worker()
    job_id = next(_job_counter)
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "project_id": project_id,
            "channel": channel,
            "params": params or {},
            "triggered_by": triggered_by,
            "status": "queued",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "run_id": None,
            "summary": None,
            "error": None,
        }
    _queue.put(job_id)
    return job_id


def get_job(job_id: int) -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def list_jobs(project_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with _jobs_lock:
        jobs = list(_jobs.values())
    if project_id is not None:
        jobs = [j for j in jobs if j["project_id"] == project_id]
    jobs.sort(key=lambda j: j["id"], reverse=True)
    return [dict(j) for j in jobs[:limit]]


def active_job() -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        for j in _jobs.values():
            if j["status"] in ("queued", "running"):
                return dict(j)
    return None


def _execute(job_id: int) -> None:
    with _jobs_lock:
        job = _jobs[job_id]
        job["status"] = "running"
        job["started_at"] = _now()
        project_id = job["project_id"]
        channel = job["channel"]
        params = job["params"]
        triggered_by = job["triggered_by"]

    summary = run_collection(project_id, channel, params, triggered_by)

    with _jobs_lock:
        job = _jobs[job_id]
        job["status"] = "done"
        job["finished_at"] = _now()
        job["run_id"] = summary.get("run_id")
        job["summary"] = summary


def run_collection(project_id: int, channel: str, params: Optional[Dict[str, Any]] = None,
                   triggered_by: Optional[str] = None) -> Dict[str, Any]:
    """Execute one collection synchronously. Used by the worker and the scheduler."""
    params = params or {}
    project = storage.get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    cfg = project["config"]

    # Image analysis is derived: gather image URLs collected by the e-commerce channel.
    if channel == "image_analysis" and not params.get("image_urls"):
        params = dict(params)
        params["image_urls"] = _gather_ecommerce_images(project_id)

    run_id = storage.start_run(project_id, channel, params, triggered_by)
    scraper = get_scraper(channel)
    try:
        result = scraper.collect(cfg, params)
    except Exception as exc:
        storage.finish_run(run_id, rows_returned=0, rows_new=0, rows_duplicate=0,
                           errors=[f"{type(exc).__name__}: {exc}"], status="error")
        raise

    counts = storage.save_items(project_id, run_id, channel, result.items)
    errors = list(result.errors)
    if result.diagnostics:
        errors.append(f"diagnostics: {result.diagnostics}")
    status = "done" if not result.errors else "done_with_errors"
    storage.finish_run(run_id, rows_returned=counts["returned"], rows_new=counts["new"],
                       rows_duplicate=counts["duplicate"], errors=errors, status=status)
    storage.audit("collection", f"{channel}: +{counts['new']} new / {counts['duplicate']} dup",
                  acting_user=triggered_by, project_id=project_id)
    return {"run_id": run_id, "channel": channel, **counts, "errors": result.errors,
            "diagnostics": result.diagnostics}


def _gather_ecommerce_images(project_id: int) -> List[str]:
    urls: List[str] = []
    for item in storage.list_items(project_id, source="ecommerce", limit=1000):
        for u in item.get("extra", {}).get("image_urls", []) or []:
            if u and u not in urls:
                urls.append(u)
    return urls
