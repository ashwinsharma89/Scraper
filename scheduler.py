"""Cron-like recurring runs, executed by a background loop.

Schedules live in the DB. A daemon thread wakes periodically, finds due schedules, and
enqueues them through the SAME single-writer job queue as manual runs — so scheduled
runs are ordinary audited runs with full lineage, never a special path.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jobs
import storage

_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_TICK_SECONDS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def create_schedule(project_id: int, channel: str, params: dict, interval_seconds: int,
                    created_by: Optional[str] = None, first_run_in: int = 0) -> int:
    next_run = _iso(_now() + timedelta(seconds=first_run_in))
    sid = storage.add_schedule(project_id, channel, params, interval_seconds, next_run, created_by)
    storage.audit("schedule.create", f"{channel} every {interval_seconds}s",
                  acting_user=created_by, project_id=project_id)
    return sid


def pause_schedule(schedule_id: int, paused: bool = True, acting_user: Optional[str] = None) -> None:
    storage.update_schedule(schedule_id, paused=1 if paused else 0)
    storage.audit("schedule.pause" if paused else "schedule.resume", f"schedule {schedule_id}",
                  acting_user=acting_user)


def delete_schedule(schedule_id: int, acting_user: Optional[str] = None) -> None:
    storage.delete_schedule(schedule_id)
    storage.audit("schedule.delete", f"schedule {schedule_id}", acting_user=acting_user)


def tick() -> int:
    """Run once: enqueue all due schedules, advance their next_run. Returns count fired."""
    fired = 0
    now = _now()
    for sched in storage.due_schedules(_iso(now)):
        jobs.enqueue(sched["project_id"], sched["channel"], sched["params"],
                     triggered_by=f"scheduler#{sched['id']}")
        next_run = _iso(now + timedelta(seconds=int(sched["interval_seconds"])))
        storage.update_schedule(sched["id"], last_run=_iso(now), next_run=next_run)
        fired += 1
    return fired


def _loop() -> None:
    while not _stop.is_set():
        try:
            tick()
        except Exception:
            pass  # never let the scheduler thread die
        _stop.wait(_TICK_SECONDS)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="marketlens-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
