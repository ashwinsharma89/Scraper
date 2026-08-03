"""A single retrying HTTP session with per-domain rate limiting.

Every network-touching scraper imports ``get_session()`` so that politeness delays
and retry policy are enforced uniformly across the whole tool. The rate limiter is
keyed by domain, so hitting Reddit does not slow down a parallel News fetch.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional
from urllib.parse import urlparse

from settings import settings


class _DomainRateLimiter:
    """Blocks so that no single domain is hit more often than ``delay`` seconds."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str, delay: Optional[float] = None) -> None:
        domain = urlparse(url).netloc.lower() or url
        d = self.delay if delay is None else delay
        with self._lock:
            now = time.monotonic()
            last = self._last.get(domain, 0.0)
            elapsed = now - last
            if elapsed < d:
                sleep_for = d - elapsed
            else:
                sleep_for = 0.0
            # Reserve the slot before releasing the lock so concurrent callers queue.
            self._last[domain] = now + sleep_for
        if sleep_for > 0:
            time.sleep(sleep_for)


class RetryingSession:
    """Thin wrapper over a ``requests.Session`` adding retries + rate limiting.

    ``requests`` is imported lazily so the module can be imported in environments
    (e.g. the minimal test install) that mock out network entirely.
    """

    def __init__(
        self,
        retries: Optional[int] = None,
        backoff_factor: float = 0.5,
        rate_limit_seconds: Optional[float] = None,
    ) -> None:
        import requests  # lazy
        from requests.adapters import HTTPAdapter

        try:
            from urllib3.util.retry import Retry
        except Exception:  # pragma: no cover - very old urllib3
            from requests.packages.urllib3.util.retry import Retry  # type: ignore

        self._retries = settings.http_retries if retries is None else retries
        rl = settings.rate_limit_seconds if rate_limit_seconds is None else rate_limit_seconds
        self._limiter = _DomainRateLimiter(rl)

        retry = Retry(
            total=self._retries,
            connect=self._retries,
            read=self._retries,
            status=self._retries,
            backoff_factor=backoff_factor,
            # 429 included: several channels (Reddit RSS in particular — verified live,
            # its rate limit is much tighter than a typical API) return 429 under normal
            # polite use, not just abuse. urllib3 automatically honors a Retry-After
            # header when present; backoff_factor covers the case where it's absent.
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST", "HEAD"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session = requests.Session()
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update({"User-Agent": settings.user_agent})

    def get(self, url: str, *, rate_delay: Optional[float] = None, **kwargs):
        self._limiter.wait(url, rate_delay)
        kwargs.setdefault("timeout", settings.http_timeout)
        return self._session.get(url, **kwargs)

    def post(self, url: str, *, rate_delay: Optional[float] = None, **kwargs):
        self._limiter.wait(url, rate_delay)
        kwargs.setdefault("timeout", settings.http_timeout)
        return self._session.post(url, **kwargs)

    @property
    def raw(self):
        return self._session


_session_singleton: Optional[RetryingSession] = None
_singleton_lock = threading.Lock()


def get_session() -> RetryingSession:
    global _session_singleton
    if _session_singleton is None:
        with _singleton_lock:
            if _session_singleton is None:
                _session_singleton = RetryingSession()
    return _session_singleton
