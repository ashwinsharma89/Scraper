"""Migrations apply incrementally to a previous-version DB without wiping data."""
import sqlite3

import migrations
import storage


def test_upgrade_from_previous_version_preserves_data(fresh_db, monkeypatch):
    # fresh_db is already at the latest version. Insert data ("previous version" state).
    pid = storage.create_project("Legacy", {"x": 1})
    assert storage.get_project(pid) is not None

    baseline = migrations.latest_version()

    # Simulate shipping a NEW migration in a later release.
    def _future_migration(conn):
        conn.execute("ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")

    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS + [_future_migration])
    assert migrations.latest_version() == baseline + 1

    # Apply upgrade against the existing (populated) DB.
    with storage.write_conn() as conn:
        new_version = migrations.apply_migrations(conn)
    assert new_version == baseline + 1

    # Data survived the upgrade AND the new column exists.
    assert storage.get_project(pid)["name"] == "Legacy"
    with storage.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()]
    assert "archived" in cols


def test_apply_to_empty_v0_db(tmp_path):
    # A brand-new DB starts at user_version 0; migrations bring it to latest with all tables.
    db = tmp_path / "v0.db"
    conn = sqlite3.connect(str(db))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    migrations.apply_migrations(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == migrations.latest_version()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for t in ("projects", "runs", "items", "analysis", "market_intel", "schedules", "users", "audit_log"):
        assert t in tables
    conn.close()
