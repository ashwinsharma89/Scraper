"""Idempotent, versioned schema migrations.

Migrations are applied on every startup by walking ``PRAGMA user_version`` forward.
Upgrading the tool never requires wiping data: each migration only ever adds to the
schema, and re-running against an already-current DB is a no-op.

To evolve the schema, append a new function to ``MIGRATIONS``. Never edit or reorder
an existing migration that may have shipped.
"""
from __future__ import annotations

import sqlite3
from typing import Callable, List


def _m001_initial(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            config_json  TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id     INTEGER NOT NULL REFERENCES projects(id),
            channel        TEXT NOT NULL,
            params_json    TEXT NOT NULL DEFAULT '{}',
            status         TEXT NOT NULL DEFAULT 'running',
            started_at     TEXT NOT NULL,
            finished_at    TEXT,
            rows_returned  INTEGER NOT NULL DEFAULT 0,
            rows_new       INTEGER NOT NULL DEFAULT 0,
            rows_duplicate INTEGER NOT NULL DEFAULT 0,
            errors_json    TEXT NOT NULL DEFAULT '[]',
            triggered_by   TEXT
        );

        CREATE TABLE IF NOT EXISTS items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id    INTEGER NOT NULL REFERENCES projects(id),
            run_id        INTEGER NOT NULL REFERENCES runs(id),
            source        TEXT NOT NULL,
            content_hash  TEXT NOT NULL,
            title         TEXT,
            text          TEXT,
            link          TEXT,
            published      TEXT,
            extra_json    TEXT NOT NULL DEFAULT '{}',
            created_at    TEXT NOT NULL,
            UNIQUE(project_id, content_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_items_project ON items(project_id);
        CREATE INDEX IF NOT EXISTS idx_items_run ON items(run_id);
        CREATE INDEX IF NOT EXISTS idx_items_source ON items(project_id, source);

        CREATE TABLE IF NOT EXISTS analysis (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id        INTEGER NOT NULL REFERENCES items(id),
            project_id     INTEGER NOT NULL REFERENCES projects(id),
            model          TEXT NOT NULL,
            sentiment      TEXT,
            sentiment_score REAL,
            language       TEXT,
            summary_en     TEXT,
            rating_signal  TEXT,
            purchase_driver TEXT,
            usage_occasion TEXT,
            trend_category TEXT,
            brand_focus    TEXT,
            promo_mentioned INTEGER,
            emotion        TEXT,
            raw_json       TEXT NOT NULL DEFAULT '{}',
            created_at     TEXT NOT NULL,
            UNIQUE(item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_analysis_project ON analysis(project_id);

        CREATE TABLE IF NOT EXISTS market_intel (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id       INTEGER NOT NULL REFERENCES projects(id),
            entry_type       TEXT NOT NULL DEFAULT 'cited',
            category         TEXT,
            metric           TEXT,
            value            TEXT,
            source_name      TEXT,
            source_url       TEXT,
            publication_date TEXT,
            accessed_date    TEXT,
            confidence       TEXT,
            notes            TEXT,
            extra_json       TEXT NOT NULL DEFAULT '{}',
            entered_by       TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_intel_project ON market_intel(project_id);

        CREATE TABLE IF NOT EXISTS schedules (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id),
            channel      TEXT NOT NULL,
            params_json  TEXT NOT NULL DEFAULT '{}',
            interval_seconds INTEGER NOT NULL,
            next_run     TEXT NOT NULL,
            last_run     TEXT,
            paused       INTEGER NOT NULL DEFAULT 0,
            created_by   TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt          TEXT NOT NULL,
            is_admin      INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER,
            action      TEXT NOT NULL,
            detail      TEXT,
            acting_user TEXT,
            created_at  TEXT NOT NULL
        );
        """
    )


def _m002_story_clusters(conn: sqlite3.Connection) -> None:
    """Near-duplicate / syndicated-story clustering.

    Syndicated wire stories (the same underlying article reprinted across several
    outlets) are legitimate distinct items — each carries its own lineage and outlet —
    but counting them as N independent data points inflates sentiment sample sizes.
    cluster_id groups near-duplicates (by title+date similarity, computed at insert
    time) WITHOUT deleting or merging rows, so exports can report both total_items
    (nothing hidden) and total_stories (syndication-adjusted n-size).
    """
    conn.executescript(
        """
        ALTER TABLE items ADD COLUMN cluster_id INTEGER;
        CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(project_id, cluster_id);
        CREATE INDEX IF NOT EXISTS idx_items_published ON items(project_id, published);
        """
    )


def _m003_category_discovery(conn: sqlite3.Connection) -> None:
    """Category-aware, multi-vertical source discovery (see DESIGN_01_category-discovery.md).

    - items.raw_html / .category / .source_type: raw-content retention (a real, previously
      absent gap — DESIGN_01 ground rule #4) plus per-item tagging so a project spanning
      several categories/source-types can be broken down in the dashboard. Only items
      collected through the new discovery pipeline populate these; existing channels are
      unaffected (columns default NULL).
    - runs.job_kind / .checkpoint_json: distinguishes a one-time historical backfill from a
      standing daily run, and lets a long, multi-source job resume from where it left off
      after a crash/restart instead of losing all progress (DESIGN_01 ground rule #5).
    - source_health: per-project, per-source circuit-breaker state — a source that fails/
      gets blocked repeatedly is auto-paused and surfaced to the operator instead of being
      retried forever or silently dropped.
    - site_intelligence: DELIBERATELY GLOBAL (no project_id) — a cross-project ledger of
      which real domains are good sources for which category, built from actual outcomes
      over time, not re-derived from scratch by every new project. See DESIGN_01 §4b.
    """
    conn.executescript(
        """
        ALTER TABLE items ADD COLUMN raw_html TEXT;
        ALTER TABLE items ADD COLUMN category TEXT;
        ALTER TABLE items ADD COLUMN source_type TEXT;

        ALTER TABLE runs ADD COLUMN job_kind TEXT;
        ALTER TABLE runs ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}';

        CREATE TABLE IF NOT EXISTS source_health (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id            INTEGER NOT NULL REFERENCES projects(id),
            source_url            TEXT NOT NULL,
            domain                TEXT NOT NULL,
            consecutive_failures  INTEGER NOT NULL DEFAULT 0,
            last_status           TEXT,
            last_checked_at       TEXT,
            paused                INTEGER NOT NULL DEFAULT 0,
            UNIQUE(project_id, source_url)
        );
        CREATE INDEX IF NOT EXISTS idx_source_health_project ON source_health(project_id);

        CREATE TABLE IF NOT EXISTS site_intelligence (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            domain              TEXT NOT NULL,
            category            TEXT NOT NULL,
            name                TEXT,
            source_type         TEXT,
            times_suggested     INTEGER NOT NULL DEFAULT 0,
            times_used          INTEGER NOT NULL DEFAULT 0,
            items_kept          INTEGER NOT NULL DEFAULT 0,
            items_dropped       INTEGER NOT NULL DEFAULT 0,
            times_blocked       INTEGER NOT NULL DEFAULT 0,
            validated_by_human  INTEGER NOT NULL DEFAULT 0,
            confidence          REAL,
            last_used_at        TEXT,
            created_at          TEXT NOT NULL,
            UNIQUE(domain, category)
        );
        CREATE INDEX IF NOT EXISTS idx_site_intel_category ON site_intelligence(category);
        """
    )


# Ordered list. Index 0 is applied to move user_version 0 -> 1, etc.
MIGRATIONS: List[Callable[[sqlite3.Connection], None]] = [
    _m001_initial,
    _m002_story_clusters,
    _m003_category_discovery,
]


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def latest_version() -> int:
    return len(MIGRATIONS)


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` up to the latest schema version. Returns the new version.

    Safe to call repeatedly; only unapplied migrations run.
    """
    version = current_version(conn)
    target = latest_version()
    for idx in range(version, target):
        migration = MIGRATIONS[idx]
        migration(conn)
        conn.execute(f"PRAGMA user_version = {idx + 1}")
        conn.commit()
    return latest_version()
