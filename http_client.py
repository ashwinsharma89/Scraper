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


def _bare_domain(domain_or_url: str) -> str:
    s = (domain_or_url or "").lower()
    if "://" in s:
        s = urlparse(s).netloc
    return s[4:] if s.startswith("www.") else s


class _DomainRateLimiter:
    """Blocks so that no single domain is hit more often than ``delay`` seconds.

    DESIGN_01_category-discovery.md §7.1: a per-call ``rate_delay`` override already
    existed (``wait(url, delay=...)``), but nothing made a "this domain needs a longer
    delay" decision stick automatically — every caller had to remember to pass it. A
    generic-site domain flagged known-sensitive should get its longer delay applied by
    every caller without each one opting in individually; ``set_domain_delay`` stores
    that as persistent per-domain state, checked when no explicit per-call override is
    given. An explicit per-call ``delay`` still wins — it's a more specific instruction
    than a standing domain default.
    """

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._last: Dict[str, float] = {}
        self._domain_overrides: Dict[str, float] = {}
        self._lock = threading.Lock()

    def set_domain_delay(self, domain: str, delay: float) -> None:
        with self._lock:
            self._domain_overrides[_bare_domain(domain)] = delay

    def get_domain_delay(self, domain: str) -> Optional[float]:
        return self._domain_overrides.get(_bare_domain(domain))

    def wait(self, url: str, delay: Optional[float] = None) -> None:
        domain = urlparse(url).netloc.lower() or url
        if delay is not None:
            d = delay
        else:
            d = self._domain_overrides.get(_bare_domain(domain), self.delay)
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


class DomainConcurrencySemaphore:
    """Per-domain concurrency cap, independent of overall worker-pool size
    (DESIGN_01 §7.2). No single domain should ever have more than ``max_concurrent``
    in-flight requests, regardless of how many *different* domains a worker pool is
    fetching in parallel — more concurrency to the SAME site is what accelerates
    blocking, not overall parallelism.

    Deliberately inert today: the current collection model (jobs.py) runs one
    channel at a time on a single worker thread, so no caller can ever present two
    concurrent requests to the same domain regardless of this class's existence.
    It's introduced now (§13 increment 5) as the primitive the worker-pool rebuild
    (§8/§9, increment 6) is specified to use, rather than inventing it later under
    time pressure — but nothing wires it into an active fetch path yet, and it does
    not affect current single-threaded behavior. Correctness is verified directly
    (real concurrent threads in tests/test_http_client.py), not left untested code.
    """

    def __init__(self, max_concurrent: int = 1) -> None:
        self.max_concurrent = max_concurrent
        self._sems: Dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()

    def _sem_for(self, domain: str) -> threading.Semaphore:
        bare = _bare_domain(domain)
        with self._lock:
            sem = self._sems.get(bare)
            if sem is None:
                sem = threading.Semaphore(self.max_concurrent)
                self._sems[bare] = sem
            return sem

    def slot(self, url_or_domain: str):
        """Context manager: blocks until a concurrency slot for this domain is free."""
        return self._sem_for(url_or_domain)


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

    def set_domain_delay(self, domain: str, delay: float) -> None:
        """Persistent per-domain rate-limit override (DESIGN_01 §7.1) — e.g. a source
        flagged known-sensitive gets a longer delay applied automatically on every
        future request to it, without each caller passing rate_delay explicitly."""
        self._limiter.set_domain_delay(domain, delay)

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


_domain_concurrency_singleton: Optional[DomainConcurrencySemaphore] = None
_concurrency_lock = threading.Lock()


def get_domain_concurrency_limiter() -> DomainConcurrencySemaphore:
    """Shared, process-wide (default max_concurrent=1 per domain) — see
    DomainConcurrencySemaphore's docstring for why this has no effect yet."""
    global _domain_concurrency_singleton
    if _domain_concurrency_singleton is None:
        with _concurrency_lock:
            if _domain_concurrency_singleton is None:
                _domain_concurrency_singleton = DomainConcurrencySemaphore()
    return _domain_concurrency_singleton
