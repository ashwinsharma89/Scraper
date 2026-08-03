"""Google Trends: retry-with-backoff around pytrends (whose own retry is broken against
the installed urllib3 — see scrapers/trends.py docstring), collect() item emission.
"""
import pandas as pd
import pytest
from pytrends.exceptions import TooManyRequestsError

from scrapers import trends


@pytest.fixture(autouse=True)
def _no_real_sleeps(monkeypatch):
    monkeypatch.setattr(trends, "RETRY_WAIT", 0)


def _rate_limit_error():
    class _Resp:
        status_code = 429
        text = "rate limited"
        reason = "Too Many Requests"
    return TooManyRequestsError.from_response(_Resp())


# --------------------------------------------------------------------------- #
# Retry wrapper
# --------------------------------------------------------------------------- #
def test_call_with_retry_succeeds_after_transient_429():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _rate_limit_error()
        return "ok"

    result = trends._call_with_retry(flaky)
    assert result == "ok"
    assert calls["n"] == 3  # failed twice, succeeded on the 3rd (2 retries)


def test_call_with_retry_gives_up_after_max_attempts():
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise _rate_limit_error()

    with pytest.raises(TooManyRequestsError):
        trends._call_with_retry(always_fails)
    assert calls["n"] == trends.RETRY_ATTEMPTS + 1  # initial try + retries


def test_call_with_retry_does_not_catch_unrelated_errors():
    def boom():
        raise ValueError("something else entirely")

    with pytest.raises(ValueError):
        trends._call_with_retry(boom)


# --------------------------------------------------------------------------- #
# collect() — pytrends mocked, no real network
# --------------------------------------------------------------------------- #
class _FakeTrendReq:
    """Mimics pytrends.request.TrendReq's public surface used by collect()."""
    def __init__(self, hl, tz):
        pass

    def build_payload(self, keywords, timeframe, geo):
        self._keywords = keywords

    def interest_over_time(self):
        idx = pd.to_datetime(["2026-01-01", "2026-01-08"])
        return pd.DataFrame({kw: [10, 40] for kw in self._keywords}, index=idx)

    def related_queries(self):
        return {self._keywords[0]: {
            "top": pd.DataFrame({"query": ["maggi price", "maggi recipe"], "value": [100, 80]}),
            "rising": pd.DataFrame({"query": ["maggi recall"], "value": [200]}),
        }}


def test_collect_emits_interest_and_related_items(monkeypatch):
    import pytrends.request
    monkeypatch.setattr(pytrends.request, "TrendReq", _FakeTrendReq)

    cfg = {"source_plan": {"trends": {"geo": "MY", "keywords": ["Maggi"]}}}
    res = trends.collect(cfg, {})

    iot_items = [i for i in res.items if i["extra"]["type"] == "interest_over_time"]
    related_items = [i for i in res.items if i["extra"]["type"].startswith("related_")]
    assert len(iot_items) == 2  # two weekly data points
    assert iot_items[0]["extra"]["relative_index"] is True
    assert len(related_items) == 3  # 2 top + 1 rising
    assert any("maggi recall" in i["text"] for i in related_items)


def test_collect_requires_keywords():
    res = trends.collect({"source_plan": {"trends": {"geo": "MY"}}}, {})
    assert res.items == []
    assert any("No keywords" in e for e in res.errors)


def test_collect_recovers_via_retry_on_transient_rate_limit(monkeypatch):
    import pytrends.request

    calls = {"n": 0}

    class _FlakyThenGood(_FakeTrendReq):
        def build_payload(self, keywords, timeframe, geo):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _rate_limit_error()
            super().build_payload(keywords, timeframe, geo)

    monkeypatch.setattr(pytrends.request, "TrendReq", _FlakyThenGood)
    cfg = {"source_plan": {"trends": {"geo": "MY", "keywords": ["Maggi"]}}}
    res = trends.collect(cfg, {})
    assert not res.errors  # recovered via retry, no error surfaced
    assert len(res.items) > 0


def test_collect_honestly_reports_persistent_failure(monkeypatch):
    import pytrends.request

    class _AlwaysFails(_FakeTrendReq):
        def build_payload(self, keywords, timeframe, geo):
            raise _rate_limit_error()

    monkeypatch.setattr(pytrends.request, "TrendReq", _AlwaysFails)
    cfg = {"source_plan": {"trends": {"geo": "MY", "keywords": ["Maggi"]}}}
    res = trends.collect(cfg, {})
    assert res.items == []
    assert any("Google Trends failed" in e for e in res.errors)
