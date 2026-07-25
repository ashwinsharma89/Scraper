"""Feed health check flags dead feeds and validates real ones (network mocked)."""
import config
import http_client


class _FakeResp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


class _FakeSession:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url, **kwargs):
        val = self.mapping[url]
        if isinstance(val, Exception):
            raise val
        return _FakeResp(*val)


GOOD_FEED = """<?xml version='1.0'?><rss version='2.0'><channel><title>Feed</title>
<item><title>Story one</title></item><item><title>Story two</title></item></channel></rss>"""


def test_feed_health_flags_dead_and_keeps_live(monkeypatch):
    urls = ["http://good/rss", "http://gone/rss", "http://notafeed/page", "http://timeout/rss"]
    fake = _FakeSession({
        "http://good/rss": (200, GOOD_FEED),
        "http://gone/rss": (404, "Not Found"),
        "http://notafeed/page": (200, "<html><body>hello</body></html>"),
        "http://timeout/rss": TimeoutError("connection timed out"),
    })
    monkeypatch.setattr(http_client, "get_session", lambda: fake)

    results = {r["url"]: r for r in config.feed_health_check(urls)}

    assert results["http://good/rss"]["healthy"] is True
    assert results["http://good/rss"]["entries"] == 2

    assert results["http://gone/rss"]["healthy"] is False
    assert "404" in results["http://gone/rss"]["reason"]

    assert results["http://notafeed/page"]["healthy"] is False
    assert "Not an RSS" in results["http://notafeed/page"]["reason"]

    assert results["http://timeout/rss"]["healthy"] is False
    assert "TimeoutError" in results["http://timeout/rss"]["reason"]
