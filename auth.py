"""Team-mode authentication — deliberately simple.

A users table (username + salted PBKDF2 hash), a signed session cookie, and an admin
user bootstrapped on first boot from env vars. No OAuth, no external identity provider.

In solo mode every request is allowed and the acting user is "solo". In team mode the
whole app is gated behind login, and every mutating action is attributed to the
authenticated user.

Secrets (admin bootstrap password, session secret) come from the environment ONLY and
are never stored in the DB in plaintext — the DB holds a salted hash.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Optional

import storage
from settings import settings

_PBKDF2_ROUNDS = 200_000
SESSION_COOKIE = "ml_session"


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ROUNDS)
    return dk.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


# --------------------------------------------------------------------------- #
# User management
# --------------------------------------------------------------------------- #
def create_user(username: str, password: str, is_admin: bool = False) -> int:
    if storage.get_user(username):
        raise ValueError(f"User '{username}' already exists")
    h, salt = hash_password(password)
    return storage.create_user(username, h, salt, is_admin)


def authenticate(username: str, password: str) -> bool:
    user = storage.get_user(username)
    if not user:
        return False
    return verify_password(password, user["password_hash"], user["salt"])


def bootstrap_admin() -> Optional[str]:
    """Create the admin user on first boot in team mode. Returns a status message."""
    if not settings.is_team:
        return None
    if storage.user_count() > 0:
        return None
    if not settings.admin_password:
        return ("TEAM MODE: no users and ADMIN_PASSWORD not set — set ADMIN_USER/ADMIN_PASSWORD "
                "in the environment and restart. Login is impossible until then.")
    create_user(settings.admin_user, settings.admin_password, is_admin=True)
    return f"TEAM MODE: bootstrapped admin user '{settings.admin_user}' from environment."


# --------------------------------------------------------------------------- #
# Sessions (signed cookies)
# --------------------------------------------------------------------------- #
def _serializer():
    from itsdangerous import URLSafeTimedSerializer

    secret = settings.session_secret or os.environ.get("SESSION_SECRET", "")
    if not secret:
        # Ephemeral secret: sessions won't survive a restart, but never insecurely blank.
        secret = secrets.token_hex(32)
    return URLSafeTimedSerializer(secret, salt="marketlens-session")


_ser = None


def _get_ser():
    global _ser
    if _ser is None:
        _ser = _serializer()
    return _ser


def make_session_token(username: str) -> str:
    return _get_ser().dumps({"u": username})


def read_session_token(token: str, max_age: int = 7 * 24 * 3600) -> Optional[str]:
    from itsdangerous import BadSignature, SignatureExpired

    try:
        data = _get_ser().loads(token, max_age=max_age)
        return data.get("u")
    except (BadSignature, SignatureExpired, Exception):
        return None


# --------------------------------------------------------------------------- #
# Request-level resolution (used by app.py dependency)
# --------------------------------------------------------------------------- #
def current_user(request) -> Optional[str]:
    """Return the acting username, or None if unauthenticated.

    Solo mode: always 'solo'. Team mode: the signed cookie's user, or None.
    """
    if not settings.is_team:
        return "solo"
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return read_session_token(token)
