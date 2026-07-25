"""Runtime settings resolved from environment variables only.

No secret is ever stored in the database in plaintext. Every knob here has a safe
default so the app boots in solo mode with zero configuration. See .env.example.
"""
from __future__ import annotations

import os
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv() -> None:
    """Best-effort .env loader (no hard dependency on python-dotenv).

    Only sets variables that are not already present in the environment, so real
    environment variables always win over the file.
    """
    env_path = os.environ.get("MARKETLENS_ENV_FILE", ".env")
    p = Path(env_path)
    if not p.exists():
        return
    try:
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    except OSError:
        pass


_load_dotenv()


class Settings:
    """Process-wide configuration. Instantiated once as ``settings`` below."""

    def __init__(self) -> None:
        # --- Storage -------------------------------------------------------
        self.data_dir: Path = Path(os.environ.get("MARKETLENS_DATA_DIR", "./data")).resolve()
        self.db_path: Path = self.data_dir / "marketlens.db"
        self.uploads_dir: Path = self.data_dir / "uploads"
        self.exports_dir: Path = self.data_dir / "exports"
        self.archives_dir: Path = self.data_dir / "archives"

        # --- Server --------------------------------------------------------
        self.mode: str = os.environ.get("MODE", "solo").strip().lower()  # solo | team
        # An empty HOST (e.g. the blank HOST= in .env.example) must fall back to the
        # mode-appropriate default, not bind to all interfaces.
        _host_env = os.environ.get("HOST", "").strip()
        self.host: str = _host_env or ("0.0.0.0" if self.is_team else "127.0.0.1")
        self.port: int = int(os.environ.get("PORT", "8000") or "8000")

        # --- Team-mode bootstrap ------------------------------------------
        self.admin_user: str = os.environ.get("ADMIN_USER", "admin")
        self.admin_password: str = os.environ.get("ADMIN_PASSWORD", "")
        self.session_secret: str = os.environ.get("SESSION_SECRET", "")

        # --- API keys (never persisted) -----------------------------------
        self.anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
        self.youtube_api_key: str = os.environ.get("YOUTUBE_API_KEY", "")
        self.places_api_key: str = os.environ.get("GOOGLE_PLACES_API_KEY", "")
        self.twitter_api_key: str = os.environ.get("TWITTER_API_KEY", "")

        # --- Analysis model -----------------------------------------------
        self.analysis_model: str = os.environ.get("ANALYSIS_MODEL", "claude-haiku-4-5")
        self.vision_model: str = os.environ.get("VISION_MODEL", "claude-haiku-4-5")

        # --- HTTP politeness ----------------------------------------------
        self.http_retries: int = int(os.environ.get("HTTP_RETRIES", "3"))
        self.rate_limit_seconds: float = float(os.environ.get("RATE_LIMIT_SECONDS", "1.5"))
        self.http_timeout: float = float(os.environ.get("HTTP_TIMEOUT", "30"))
        self.user_agent: str = os.environ.get(
            "HTTP_USER_AGENT",
            "MarketLens/{v} (research; +https://localhost)".format(v="0.1.0"),
        )

    @property
    def is_team(self) -> bool:
        return os.environ.get("MODE", "solo").strip().lower() == "team"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.exports_dir, self.archives_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
