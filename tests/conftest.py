"""Shared pytest fixtures. All network is mocked; tests never hit the internet."""
import sys
from pathlib import Path

import pytest

# Make the project root importable (tests/ is a subdir).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Isolated SQLite DB + data dir per test."""
    import settings as settings_mod
    import storage

    data_dir = tmp_path / "data"
    s = settings_mod.settings
    monkeypatch.setattr(s, "data_dir", data_dir)
    monkeypatch.setattr(s, "db_path", data_dir / "marketlens.db")
    monkeypatch.setattr(s, "uploads_dir", data_dir / "uploads")
    monkeypatch.setattr(s, "exports_dir", data_dir / "exports")
    monkeypatch.setattr(s, "archives_dir", data_dir / "archives")

    storage._initialized = False
    storage.init_db()
    yield storage
    storage._initialized = False
