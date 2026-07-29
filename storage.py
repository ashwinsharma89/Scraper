"""Persistence, lineage, and cross-run de-duplication.

Design principles enforced here (decision-grade data):
  * Nothing lives only in memory: every collected item is written with a run_id FK,
    giving full lineage back to the run (and its params) that produced it.
  * Counts are never inflated by duplicates: a content hash uniquely identifies an
    item *within a project*; re-collecting the same content is recorded as a
    duplicate against the new run, not stored twice.
  * Project isolation: the same content hash can coexist across projects (each row
    is scoped by project_id), so two studies never contaminate each other.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import migrations
from settings import settings

# A single process-wide write lock. Combined with SQLite WAL this gives us the
# "single-writer, many-reader" guarantee the spec asks for, so concurrent scrape
# jobs / API mutations can never corrupt state.
_write_lock = threading.RLock()
_init_lock = threading.Lock()
_initialized = False


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    settings.ensure_dirs()
    conn = sqlite3.connect(str(settings.db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db() -> None:
    """Apply migrations. Idempotent; safe to call on every startup."""
    global _initialized
    with _init_lock:
        conn = _connect()
        try:
            migrations.apply_migrations(conn)
        finally:
            conn.close()
        _initialized = True


@contextmanager
def get_conn():
    """Read/small-write connection. Callers that mutate should hold the write lock."""
    if not _initialized:
        init_db()
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def write_conn():
    """Serialized writer context: acquires the global write lock for its lifetime."""
    if not _initialized:
        init_db()
    with _write_lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Content hashing / dedup
# --------------------------------------------------------------------------- #
def compute_content_hash(source: str, link: str, title: str, text: str) -> str:
    """Stable content identity.

    Deliberately does NOT include project_id: identical content in two projects
    yields the same hash, and project isolation is enforced by the composite
    UNIQUE(project_id, content_hash) constraint instead. This lets the same item
    legitimately exist once per project.
    """
    norm = "|".join(
        [
            (source or "").strip().lower(),
            (link or "").strip(),
            (title or "").strip(),
            (text or "")[:200].strip(),
        ]
    )
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #
def create_project(name: str, config: Dict[str, Any]) -> int:
    now = utcnow()
    with write_conn() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, config_json, created_at, updated_at) VALUES (?,?,?,?)",
            (name, json.dumps(config, ensure_ascii=False), now, now),
        )
        return int(cur.lastrowid)


def update_project_config(project_id: int, config: Dict[str, Any], name: Optional[str] = None) -> None:
    with write_conn() as conn:
        if name is not None:
            conn.execute(
                "UPDATE projects SET config_json=?, name=?, updated_at=? WHERE id=?",
                (json.dumps(config, ensure_ascii=False), name, utcnow(), project_id),
            )
        else:
            conn.execute(
                "UPDATE projects SET config_json=?, updated_at=? WHERE id=?",
                (json.dumps(config, ensure_ascii=False), utcnow(), project_id),
            )


def get_project(project_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d.pop("config_json"))
    return d


def list_projects() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT id, name, created_at, updated_at FROM projects ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def delete_project(project_id: int) -> None:
    """Explicit, confirmed purge of an entire project and all its lineage."""
    with write_conn() as conn:
        conn.execute("DELETE FROM analysis WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM items WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM runs WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM market_intel WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM schedules WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


# --------------------------------------------------------------------------- #
# Runs (lineage)
# --------------------------------------------------------------------------- #
def start_run(project_id: int, channel: str, params: Dict[str, Any], triggered_by: Optional[str] = None) -> int:
    with write_conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (project_id, channel, params_json, status, started_at, triggered_by) "
            "VALUES (?,?,?,?,?,?)",
            (project_id, channel, json.dumps(params, ensure_ascii=False), "running", utcnow(), triggered_by),
        )
        return int(cur.lastrowid)


def finish_run(
    run_id: int,
    *,
    rows_returned: int,
    rows_new: int,
    rows_duplicate: int,
    errors: Optional[List[str]] = None,
    status: str = "done",
) -> None:
    with write_conn() as conn:
        conn.execute(
            "UPDATE runs SET status=?, finished_at=?, rows_returned=?, rows_new=?, rows_duplicate=?, errors_json=? "
            "WHERE id=?",
            (
                status,
                utcnow(),
                rows_returned,
                rows_new,
                rows_duplicate,
                json.dumps(errors or [], ensure_ascii=False),
                run_id,
            ),
        )


def get_run(run_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(project_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE project_id=? ORDER BY id DESC LIMIT ?", (project_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Near-duplicate / syndicated-story clustering
# --------------------------------------------------------------------------- #
# A wire story reprinted across outlets is NOT the same content_hash (different link,
# often a slightly different title/lede), so exact dedup correctly stores each as a
# distinct item — each has its own lineage and outlet. But counting 5 reprints of one
# story as 5 independent sentiment data points inflates the apparent n-size. Clustering
# groups near-duplicates (by title similarity within a tight date window) WITHOUT
# deleting or merging any row, so total_items stays honest and analytics can also
# report total_stories (syndication-adjusted).
_CLUSTER_WINDOW_DAYS = 2
_CLUSTER_SIMILARITY_THRESHOLD = 0.82
# Trailing " - Outlet Name" / " | Outlet Name" style suffixes that feeds commonly
# append; stripped before comparing so the same story from two outlets still matches.
_OUTLET_SUFFIX_RE = re.compile(r"\s*[-|–—]\s*[A-Za-z0-9.&' ]{2,40}$")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize_title_for_clustering(title: str) -> str:
    t = (title or "").strip()
    t = _OUTLET_SUFFIX_RE.sub("", t)
    t = _PUNCT_RE.sub(" ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _parse_pub_date(published: Optional[str]):
    if not published:
        return None
    try:
        return date.fromisoformat(str(published)[:10])
    except ValueError:
        return None


def _find_cluster_match(conn: sqlite3.Connection, project_id: int, title: str,
                        published: Optional[str]) -> Optional[int]:
    """Return the cluster_id to adopt if this item is a near-duplicate of an existing
    one, else None (it becomes its own singleton cluster)."""
    norm = _normalize_title_for_clustering(title)
    if not norm:
        return None
    pub = _parse_pub_date(published)
    if pub is None:
        return None  # no date -> can't safely bound the comparison window

    lo = (pub - timedelta(days=_CLUSTER_WINDOW_DAYS)).isoformat()
    hi = (pub + timedelta(days=_CLUSTER_WINDOW_DAYS)).isoformat()
    candidates = conn.execute(
        "SELECT id, title, cluster_id FROM items WHERE project_id=? AND published BETWEEN ? AND ?",
        (project_id, lo, hi),
    ).fetchall()

    best_id, best_ratio = None, 0.0
    for row in candidates:
        cand_norm = _normalize_title_for_clustering(row["title"])
        if not cand_norm:
            continue
        ratio = difflib.SequenceMatcher(None, norm, cand_norm).ratio()
        if ratio > best_ratio:
            best_ratio, best_id = ratio, row
    if best_id is not None and best_ratio >= _CLUSTER_SIMILARITY_THRESHOLD:
        # Adopt the match's existing cluster (it may already represent a cluster of
        # several items); if the match is itself still a singleton, its own id becomes
        # the cluster id for both.
        return best_id["cluster_id"] if best_id["cluster_id"] is not None else best_id["id"]
    return None


# --------------------------------------------------------------------------- #
# Items (with dedup)
# --------------------------------------------------------------------------- #
def save_items(project_id: int, run_id: int, source: str, items: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Persist collected items, de-duplicating within the project.

    Each item dict may provide: title, text, link, published, extra (dict).
    Returns {"returned": N, "new": N, "duplicate": N}. The run's counters are the
    caller's responsibility (call finish_run with these numbers).
    """
    returned = 0
    new = 0
    dup = 0
    now = utcnow()
    with write_conn() as conn:
        for it in items:
            returned += 1
            title = it.get("title") or ""
            text = it.get("text") or ""
            link = it.get("link") or ""
            published = it.get("published")
            extra = it.get("extra") or {}
            chash = it.get("content_hash") or compute_content_hash(source, link, title, text)
            exists = conn.execute(
                "SELECT 1 FROM items WHERE project_id=? AND content_hash=?", (project_id, chash)
            ).fetchone()
            if exists:
                dup += 1
                continue
            try:
                cur = conn.execute(
                    "INSERT INTO items (project_id, run_id, source, content_hash, title, text, link, "
                    "published, extra_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_id,
                        run_id,
                        source,
                        chash,
                        title,
                        text,
                        link,
                        published,
                        json.dumps(extra, ensure_ascii=False),
                        now,
                    ),
                )
                new_id = cur.lastrowid
                # Near-duplicate clustering: assign AFTER insert so this item is itself
                # a candidate for later inserts in the same batch (chained syndication).
                match_cluster = _find_cluster_match(conn, project_id, title, published)
                cluster_id = match_cluster if match_cluster is not None else new_id
                conn.execute("UPDATE items SET cluster_id=? WHERE id=?", (cluster_id, new_id))
                new += 1
            except sqlite3.IntegrityError:
                # Lost a race on the UNIQUE constraint -> it's a duplicate.
                dup += 1
    return {"returned": returned, "new": new, "duplicate": dup}


def count_unique_stories(project_id: int, source: Optional[str] = None) -> int:
    """Syndication-adjusted item count: distinct cluster_id (each singleton item is its
    own cluster, so this is <= total item count, never inflated by wire-story reprints).

    COALESCE(cluster_id, id): SQL's COUNT(DISTINCT x) does not count NULLs at all, which
    would silently undercount rows written before this feature existed (cluster_id is
    NULL on legacy rows). Falling back to the row's own id treats every such row as its
    own singleton story, which is exactly correct — it just wasn't clustered yet.
    """
    q = "SELECT COUNT(DISTINCT COALESCE(cluster_id, id)) c FROM items WHERE project_id=?"
    args: List[Any] = [project_id]
    if source:
        q += " AND source=?"
        args.append(source)
    with get_conn() as conn:
        row = conn.execute(q, args).fetchone()
    return int(row["c"] or 0)


def cluster_sizes(project_id: int) -> Dict[int, int]:
    """cluster_id -> number of items in that cluster (>1 means syndicated across outlets).
    Legacy rows with no cluster_id are treated as their own singleton (see count_unique_stories)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT COALESCE(cluster_id, id) AS cid, COUNT(*) n FROM items WHERE project_id=? GROUP BY cid",
            (project_id,),
        ).fetchall()
    return {r["cid"]: r["n"] for r in rows}


def get_item(item_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["extra"] = json.loads(d.get("extra_json") or "{}")
    return d


def list_items(
    project_id: int,
    source: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
    published_after: Optional[str] = None,
    published_before: Optional[str] = None,
) -> List[Dict[str, Any]]:
    q = "SELECT * FROM items WHERE project_id=?"
    args: List[Any] = [project_id]
    if source:
        q += " AND source=?"
        args.append(source)
    if published_after:
        q += " AND published >= ?"
        args.append(published_after)
    if published_before:
        q += " AND published <= ?"
        args.append(published_before)
    q += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    with get_conn() as conn:
        rows = conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["extra"] = json.loads(d.get("extra_json") or "{}")
        out.append(d)
    return out


def count_items_by_source(project_id: int) -> Dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) c FROM items WHERE project_id=? GROUP BY source", (project_id,)
        ).fetchall()
    return {r["source"]: r["c"] for r in rows}


def get_unanalyzed_items(project_id: int, limit: int = 12) -> List[Dict[str, Any]]:
    """Items in a project that have no analysis row yet (drives idempotent /analyze)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT i.* FROM items i "
            "LEFT JOIN analysis a ON a.item_id = i.id "
            "WHERE i.project_id=? AND a.id IS NULL ORDER BY i.id LIMIT ?",
            (project_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["extra"] = json.loads(d.get("extra_json") or "{}")
        out.append(d)
    return out


def count_unanalyzed(project_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM items i LEFT JOIN analysis a ON a.item_id=i.id "
            "WHERE i.project_id=? AND a.id IS NULL",
            (project_id,),
        ).fetchone()
    return int(row["c"])


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
def save_analysis(project_id: int, item_id: int, model: str, tags: Dict[str, Any]) -> bool:
    """Upsert-guarded: idempotent. Returns True if a new row was written."""
    with write_conn() as conn:
        exists = conn.execute("SELECT 1 FROM analysis WHERE item_id=?", (item_id,)).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO analysis (item_id, project_id, model, sentiment, sentiment_score, language, "
            "summary_en, rating_signal, purchase_driver, usage_occasion, trend_category, brand_focus, "
            "promo_mentioned, emotion, raw_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item_id,
                project_id,
                model,
                tags.get("sentiment"),
                tags.get("sentiment_score"),
                tags.get("language"),
                tags.get("summary_en"),
                tags.get("rating_signal"),
                tags.get("purchase_driver"),
                tags.get("usage_occasion"),
                tags.get("trend_category"),
                tags.get("brand_focus"),
                1 if tags.get("promo_mentioned") else 0,
                tags.get("emotion"),
                json.dumps(tags, ensure_ascii=False),
                utcnow(),
            ),
        )
        return True


def get_analysis_for_item(item_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM analysis WHERE item_id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def items_with_analysis(project_id: int, source: Optional[str] = None) -> List[Dict[str, Any]]:
    q = (
        "SELECT i.*, a.sentiment, a.sentiment_score, a.language, a.summary_en, a.rating_signal, "
        "a.purchase_driver, a.usage_occasion, a.trend_category, a.brand_focus, a.promo_mentioned, "
        "a.emotion, a.model AS analysis_model FROM items i LEFT JOIN analysis a ON a.item_id=i.id "
        "WHERE i.project_id=?"
    )
    args: List[Any] = [project_id]
    if source:
        q += " AND i.source=?"
        args.append(source)
    q += " ORDER BY i.id"
    with get_conn() as conn:
        rows = conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["extra"] = json.loads(d.get("extra_json") or "{}")
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# Market intel (cited layer + manual ad intel)
# --------------------------------------------------------------------------- #
def add_market_intel(project_id: int, entry: Dict[str, Any], entered_by: Optional[str] = None) -> int:
    now = utcnow()
    with write_conn() as conn:
        cur = conn.execute(
            "INSERT INTO market_intel (project_id, entry_type, category, metric, value, source_name, "
            "source_url, publication_date, accessed_date, confidence, notes, extra_json, entered_by, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                project_id,
                entry.get("entry_type", "cited"),
                entry.get("category"),
                entry.get("metric"),
                entry.get("value"),
                entry.get("source_name"),
                entry.get("source_url"),
                entry.get("publication_date"),
                entry.get("accessed_date"),
                entry.get("confidence"),
                entry.get("notes"),
                json.dumps(entry.get("extra") or {}, ensure_ascii=False),
                entered_by,
                now,
                now,
            ),
        )
        return int(cur.lastrowid)


def list_market_intel(project_id: int, entry_type: Optional[str] = None) -> List[Dict[str, Any]]:
    q = "SELECT * FROM market_intel WHERE project_id=?"
    args: List[Any] = [project_id]
    if entry_type:
        q += " AND entry_type=?"
        args.append(entry_type)
    q += " ORDER BY id"
    with get_conn() as conn:
        rows = conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["extra"] = json.loads(d.get("extra_json") or "{}")
        out.append(d)
    return out


def delete_market_intel(project_id: int, intel_id: int) -> None:
    with write_conn() as conn:
        conn.execute("DELETE FROM market_intel WHERE id=? AND project_id=?", (intel_id, project_id))


# --------------------------------------------------------------------------- #
# Schedules
# --------------------------------------------------------------------------- #
def add_schedule(
    project_id: int,
    channel: str,
    params: Dict[str, Any],
    interval_seconds: int,
    next_run: str,
    created_by: Optional[str] = None,
) -> int:
    now = utcnow()
    with write_conn() as conn:
        cur = conn.execute(
            "INSERT INTO schedules (project_id, channel, params_json, interval_seconds, next_run, "
            "paused, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (project_id, channel, json.dumps(params, ensure_ascii=False), interval_seconds, next_run, 0,
             created_by, now, now),
        )
        return int(cur.lastrowid)


def list_schedules(project_id: Optional[int] = None) -> List[Dict[str, Any]]:
    if project_id is None:
        q, args = "SELECT * FROM schedules ORDER BY id", []
    else:
        q, args = "SELECT * FROM schedules WHERE project_id=? ORDER BY id", [project_id]
    with get_conn() as conn:
        rows = conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d.get("params_json") or "{}")
        out.append(d)
    return out


def due_schedules(now_iso: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE paused=0 AND next_run <= ? ORDER BY id", (now_iso,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d.get("params_json") or "{}")
        out.append(d)
    return out


def update_schedule(schedule_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with write_conn() as conn:
        conn.execute(f"UPDATE schedules SET {cols}, updated_at=? WHERE id=?",
                     (*fields.values(), utcnow(), schedule_id))


def delete_schedule(schedule_id: int) -> None:
    with write_conn() as conn:
        conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))


# --------------------------------------------------------------------------- #
# Audit log (multi-user attribution)
# --------------------------------------------------------------------------- #
def audit(action: str, detail: str = "", acting_user: Optional[str] = None, project_id: Optional[int] = None) -> None:
    with write_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (project_id, action, detail, acting_user, created_at) VALUES (?,?,?,?,?)",
            (project_id, action, detail, acting_user, utcnow()),
        )


def list_audit(project_id: Optional[int] = None, limit: int = 300) -> List[Dict[str, Any]]:
    if project_id is None:
        q, args = "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", [limit]
    else:
        q, args = "SELECT * FROM audit_log WHERE project_id=? ORDER BY id DESC LIMIT ?", [project_id, limit]
    with get_conn() as conn:
        rows = conn.execute(q, args).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Users (team mode)
# --------------------------------------------------------------------------- #
def create_user(username: str, password_hash: str, salt: str, is_admin: bool = False) -> int:
    with write_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, salt, is_admin, created_at) VALUES (?,?,?,?,?)",
            (username, password_hash, salt, 1 if is_admin else 0, utcnow()),
        )
        return int(cur.lastrowid)


def get_user(username: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def user_count() -> int:
    with get_conn() as conn:
        return int(conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"])
