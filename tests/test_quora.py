"""Quora: honest, specific block reporting (never fabricates on failure).

Live-verified against real Quora question URLs: every request hits a Cloudflare
managed bot-challenge (403, "Just a moment..." JS-challenge page), universal across
URLs and User-Agents — not fixable without executing JavaScript in a real browser.
These tests lock in that the channel reports this SPECIFICALLY rather than a generic
"likely blocked", using the real challenge-page markers captured live.
"""
from scrapers import quora

# A trimmed but structurally real fragment of Quora's actual Cloudflare challenge page
# (captured live) — the markers this fixture relies on are the ones actually present.
CLOUDFLARE_CHALLENGE_HTML = """<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>
<meta http-equiv="content-security-policy" content="default-src 'none'; script-src 'nonce-x'
'unsafe-eval' https://challenges.cloudflare.com;"></head><body>
<div class="main-content"><noscript><span id="challenge-error-text">Enable JavaScript and
cookies to continue</span></noscript></div>
<script>window._cf_chl_opt = {cRay: 'a2570d1419d6a843', cType: 'managed'};
var a = document.createElement('script'); a.src = '/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1';
</script></body></html>"""

LOGIN_WALL_HTML = "<html><body>Log In or Sign Up to continue browsing Quora</body></html>"

CAPTCHA_HTML = "<html><body>Please complete the CAPTCHA to continue.</body></html>"

REAL_ANSWER_HTML = """<html><head><title>Is Maggi healthy? - Quora</title></head>
<body><article><h1>Is Maggi healthy?</h1>
<p>Maggi noodles are convenient but high in sodium; moderation is key according to most
nutritionists who have reviewed the ingredient list.</p></article></body></html>"""


class _Resp:
    def __init__(self, text="", status=200):
        self.text = text
        self.status_code = status


def _cfg():
    return {"relevance_terms": ["Maggi"], "source_plan": {"quora_topics": ["https://www.quora.com/q1"]}}


# --------------------------------------------------------------------------- #
# Detection helpers
# --------------------------------------------------------------------------- #
def test_cloudflare_challenge_detected():
    assert quora._cloudflare_challenge(CLOUDFLARE_CHALLENGE_HTML) is True
    assert quora._cloudflare_challenge(REAL_ANSWER_HTML) is False


def test_block_reason_is_specific_not_generic():
    reason = quora._block_reason(403, CLOUDFLARE_CHALLENGE_HTML)
    assert "Cloudflare" in reason and "JavaScript" in reason
    assert reason != "HTTP 403 (likely blocked). Logged, not fabricated."  # not the generic fallback

    assert "CAPTCHA" in quora._block_reason(403, CAPTCHA_HTML)
    assert "login/signup" in quora._block_reason(403, LOGIN_WALL_HTML)
    # Truly unknown block reason still gets an honest, if generic, message.
    assert "likely blocked" in quora._block_reason(403, "<html>mystery</html>")


# --------------------------------------------------------------------------- #
# End-to-end collect()
# --------------------------------------------------------------------------- #
def test_collect_reports_cloudflare_challenge_specifically_no_fabrication():
    def fetch(url):
        return _Resp(CLOUDFLARE_CHALLENGE_HTML, status=403)

    res = quora.collect(_cfg(), {}, fetch_fn=fetch)
    assert res.items == []  # nothing fabricated
    assert len(res.errors) == 1
    assert "Cloudflare" in res.errors[0]
    assert "not fixable without a real browser" in res.errors[0]


def test_collect_keeps_relevant_real_answer():
    def fetch(url):
        return _Resp(REAL_ANSWER_HTML, status=200)

    res = quora.collect(_cfg(), {}, fetch_fn=fetch)
    assert len(res.items) == 1
    assert "sodium" in res.items[0]["text"].lower()
    assert res.errors == []


def test_collect_drops_irrelevant_real_page():
    html = "<html><head><title>Unrelated question</title></head><body><article><p>Nothing to do with the topic.</p></article></body></html>"

    def fetch(url):
        return _Resp(html, status=200)

    res = quora.collect({"relevance_terms": ["Maggi"], "source_plan": {"quora_topics": ["https://www.quora.com/q1"]}},
                        {}, fetch_fn=fetch)
    assert res.items == []
    assert res.errors == []  # not blocked, just irrelevant — no error needed


def test_collect_continues_after_one_url_blocked():
    """One blocked URL must not stop collection of the rest — graceful per-URL handling."""
    def fetch(url):
        if url == "https://www.quora.com/blocked":
            return _Resp(CLOUDFLARE_CHALLENGE_HTML, status=403)
        return _Resp(REAL_ANSWER_HTML, status=200)

    cfg = {"relevance_terms": ["Maggi"],
           "source_plan": {"quora_topics": ["https://www.quora.com/blocked", "https://www.quora.com/ok"]}}
    res = quora.collect(cfg, {}, fetch_fn=fetch)
    assert len(res.items) == 1  # the second URL still succeeded
    assert len(res.errors) == 1  # the first URL's block is still logged


def test_collect_requires_urls():
    res = quora.collect({"relevance_terms": [], "source_plan": {}}, {}, fetch_fn=lambda u: _Resp())
    assert res.items == []
    assert any("No Quora question URLs" in e for e in res.errors)
