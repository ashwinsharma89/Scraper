"""Generic fetch/parse pipeline (DESIGN_01_category-discovery.md §5, Increment 3).

Network is mocked via fetch_fn injection (scrapers/news.py's established convention)
so nothing here makes a real request. One test also runs a REAL recorded article page
(tests/fixtures/generic_site_real_article.html — a live thebetterindia.com article,
saved verbatim, not synthesized) through the actual trafilatura extraction step, so
this isn't only testing against hand-crafted HTML that happens to be easy to parse.
"""
import os

import pytest

from scrapers import generic_site


class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures",
                            "generic_site_real_article.html")

REAL_ARTICLE_URL = ("https://thebetterindia.com/changemakers/"
                    "kodaikanal-school-on-wheels-tribal-first-generation-students-12520658")

ARTICLE_HTML = """<html><head><title>A real article title</title></head>
<body><article>
<h1>A real article title</h1>
<p>This is the first paragraph of a genuine article with enough substantive content to
clear the minimum content length threshold used to distinguish real articles from
boilerplate or blocked pages.</p>
<p>A second paragraph continues the story with more real detail, names, and context so
that trafilatura's readability-style extraction has a clear main-content block to find,
distinct from any navigation chrome or footer links on the page.</p>
<p>A third paragraph rounds out the piece with a concluding thought, safely pushing the
total extracted text past the three-hundred-character floor checked by the pipeline.</p>
</article>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
</body></html>"""

BLOCKED_HTML_TEXT_MARKER = """<html><body>
<div>Please verify you are human before continuing. Access denied.</div>
</body></html>"""

TOO_SHORT_HTML = """<html><body><p>Hi there.</p></body></html>"""

TOO_SHORT_WITH_CAPTCHA_WIDGET = """<html><body>
<div id="challenge">Loading...</div>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" data-sitekey="cf-turnstile"></script>
</body></html>"""


def _fetch_fn_for(html, status=200):
    def fetch(url):
        return _Resp(html, status=status)
    return fetch


def test_fetch_and_extract_returns_real_content_from_a_normal_article():
    r = generic_site.fetch_and_extract("http://example.com/article",
                                        fetch_fn=_fetch_fn_for(ARTICLE_HTML))
    assert r["ok"] is True
    assert r["title"] == "A real article title"
    assert "first paragraph" in r["text"]
    assert "third paragraph" in r["text"]
    assert r["raw_html"] == ARTICLE_HTML
    assert r["url"] == "http://example.com/article"


def test_fetch_and_extract_rejects_empty_url():
    r = generic_site.fetch_and_extract("", fetch_fn=_fetch_fn_for(ARTICLE_HTML))
    assert r["ok"] is False
    assert "empty url" in r["error"]


def test_fetch_and_extract_reports_fetch_exception_honestly():
    def boom(url):
        raise ConnectionError("dns failure")
    r = generic_site.fetch_and_extract("http://example.com/x", fetch_fn=boom)
    assert r["ok"] is False
    assert "fetch failed" in r["error"]
    assert "dns failure" in r["error"]


def test_fetch_and_extract_reports_http_error_status():
    r = generic_site.fetch_and_extract("http://example.com/404",
                                        fetch_fn=_fetch_fn_for("not found", status=404))
    assert r["ok"] is False
    assert "404" in r["error"]


def test_fetch_and_extract_detects_visible_block_marker():
    r = generic_site.fetch_and_extract("http://example.com/blocked",
                                        fetch_fn=_fetch_fn_for(BLOCKED_HTML_TEXT_MARKER))
    assert r["ok"] is False
    assert "blocked" in r["error"]
    assert "access denied" in r["error"]


def test_fetch_and_extract_rejects_content_shorter_than_min_length():
    r = generic_site.fetch_and_extract("http://example.com/thin",
                                        fetch_fn=_fetch_fn_for(TOO_SHORT_HTML))
    assert r["ok"] is False
    assert "too short" in r["error"] or "no extractable" in r["error"]
    assert "CAPTCHA" not in r["error"]  # no widget present -- no false enrichment


def test_fetch_and_extract_thin_page_with_captcha_widget_gets_a_sharper_error():
    """A widget alone doesn't veto pre-extraction (see module docstring's real false-
    positive note) -- but when the page ALSO turns out to have no real content, the
    widget evidence should sharpen the error message, not just say "too short"."""
    r = generic_site.fetch_and_extract("http://example.com/captcha",
                                        fetch_fn=_fetch_fn_for(TOO_SHORT_WITH_CAPTCHA_WIDGET))
    assert r["ok"] is False
    assert "cf-turnstile" in r["error"] or "captcha" in r["error"].lower()


def test_fetch_and_extract_does_not_flag_a_real_article_that_merely_embeds_a_captcha_widget():
    """The exact real false positive found while building this: a genuine, fully
    extractable article whose page also embeds an unrelated reCAPTCHA widget (e.g.
    for its comment form) must NOT be misclassified as blocked."""
    html_with_incidental_widget = ARTICLE_HTML.replace(
        "</body>", '<script src="https://www.google.com/recaptcha/api.js"></script></body>')
    r = generic_site.fetch_and_extract("http://example.com/article-with-widget",
                                        fetch_fn=_fetch_fn_for(html_with_incidental_widget))
    assert r["ok"] is True
    assert "first paragraph" in r["text"]


def test_fetch_and_extract_missing_trafilatura_is_an_honest_skip(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "trafilatura":
            raise ImportError("no module named trafilatura")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = generic_site.fetch_and_extract("http://example.com/article",
                                        fetch_fn=_fetch_fn_for(ARTICLE_HTML))
    assert r["ok"] is False
    assert "trafilatura is not installed" in r["error"]


@pytest.mark.skipif(not os.path.exists(FIXTURE_PATH),
                    reason="real recorded article fixture not present")
def test_fetch_and_extract_against_a_real_recorded_article_page():
    """Not synthetic HTML — a real thebetterindia.com article page saved verbatim
    (see fixture header comment in the test module docstring). Confirms the pipeline
    works against genuine site markup, not just hand-crafted test fixtures."""
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        real_html = f.read()

    r = generic_site.fetch_and_extract(REAL_ARTICLE_URL, fetch_fn=_fetch_fn_for(real_html))
    assert r["ok"] is True
    assert "Kodaikanal" in r["title"] or "Tamil Nadu" in r["title"]
    assert len(r["text"]) > 2000  # a real, substantial article body, not a stub
    assert r["author"]  # trafilatura found a byline on the real page
