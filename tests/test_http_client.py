"""Per-domain rate override + concurrency-cap primitive (DESIGN_01 §7.1/§7.2,
increment 5). No real network here -- these test the rate-limiting/semaphore
mechanics directly, not requests.Session behavior."""
import threading
import time

from http_client import DomainConcurrencySemaphore, _DomainRateLimiter, _bare_domain


def test_bare_domain_strips_scheme_and_www():
    assert _bare_domain("https://www.Example.com/path") == "example.com"
    assert _bare_domain("example.com") == "example.com"
    assert _bare_domain("") == ""


def test_rate_limiter_uses_global_default_with_no_override():
    limiter = _DomainRateLimiter(delay=0.05)
    t0 = time.monotonic()
    limiter.wait("http://example.com/a")
    limiter.wait("http://example.com/b")
    assert time.monotonic() - t0 >= 0.05


def test_rate_limiter_per_domain_override_applies_automatically():
    limiter = _DomainRateLimiter(delay=0.01)
    limiter.set_domain_delay("sensitive.com", 0.08)
    assert limiter.get_domain_delay("sensitive.com") == 0.08
    assert limiter.get_domain_delay("other.com") is None

    t0 = time.monotonic()
    limiter.wait("https://sensitive.com/a")
    limiter.wait("https://sensitive.com/b")  # no explicit rate_delay passed
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.08  # the persistent override applied, not the 0.01 default


def test_rate_limiter_explicit_call_override_still_wins_over_domain_default():
    limiter = _DomainRateLimiter(delay=0.01)
    limiter.set_domain_delay("sensitive.com", 0.5)  # would make the test slow if honored
    t0 = time.monotonic()
    limiter.wait("https://sensitive.com/a")
    limiter.wait("https://sensitive.com/b", delay=0.0)  # explicit per-call override wins
    assert time.monotonic() - t0 < 0.5


def test_rate_limiter_override_is_domain_specific_not_global():
    limiter = _DomainRateLimiter(delay=0.01)
    limiter.set_domain_delay("sensitive.com", 0.2)
    t0 = time.monotonic()
    limiter.wait("https://other.com/a")
    limiter.wait("https://other.com/b")
    assert time.monotonic() - t0 < 0.2  # unrelated domain unaffected


def test_domain_concurrency_semaphore_serializes_same_domain_real_threads():
    """Real threads, not mocked -- proves the primitive actually enforces the cap,
    even though nothing calls it in the current single-threaded collection model."""
    sem = DomainConcurrencySemaphore(max_concurrent=1)
    concurrent_count = {"current": 0, "max_seen": 0}
    lock = threading.Lock()

    def worker():
        with sem.slot("shared.com"):
            with lock:
                concurrent_count["current"] += 1
                concurrent_count["max_seen"] = max(concurrent_count["max_seen"],
                                                   concurrent_count["current"])
            time.sleep(0.05)
            with lock:
                concurrent_count["current"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert concurrent_count["max_seen"] == 1


def test_domain_concurrency_semaphore_different_domains_run_in_parallel():
    sem = DomainConcurrencySemaphore(max_concurrent=1)
    concurrent_count = {"current": 0, "max_seen": 0}
    lock = threading.Lock()

    def worker(domain):
        with sem.slot(domain):
            with lock:
                concurrent_count["current"] += 1
                concurrent_count["max_seen"] = max(concurrent_count["max_seen"],
                                                   concurrent_count["current"])
            time.sleep(0.05)
            with lock:
                concurrent_count["current"] -= 1

    threads = [threading.Thread(target=worker, args=(f"domain{i}.com",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert concurrent_count["max_seen"] == 5  # different domains never block each other
