"""Strict relevance: drops related-links-only matches, keeps real body matches."""
from scrapers import relevance

TERMS = ["Acme Cola", "Fizzly"]

# The term appears ONLY inside a related-articles rail, never in the real article body.
PAGE_RELATED_ONLY = """
<html><body>
  <article>
    <h1>Beverage industry sees packaging changes this quarter</h1>
    <p>Manufacturers across the sector are revising bottle designs to cut plastic use.</p>
    <p>Analysts expect the trend to continue through the year.</p>
  </article>
  <aside class="related-articles">
    <h3>Related</h3>
    <ul>
      <li><a href="/x">Acme Cola launches new flavor</a></li>
      <li><a href="/y">Fizzly expands distribution</a></li>
    </ul>
  </aside>
  <div class="more-from-us"><a>Acme Cola quarterly results</a></div>
</body></html>
"""

# The term appears in the genuine article body.
PAGE_BODY_MATCH = """
<html><body>
  <nav><a>Home</a><a>News</a></nav>
  <article>
    <h1>Local drinks market update</h1>
    <p>Acme Cola reported a strong quarter, driven by its sugar-free line.</p>
    <p>Retailers noted steady demand across supermarkets.</p>
  </article>
  <div class="related"><a>Fizzly news</a></div>
  <footer>Copyright</footer>
</body></html>
"""


def test_extract_main_text_strips_related_block():
    text = relevance.extract_main_text(PAGE_RELATED_ONLY)
    assert "packaging changes" in text.lower() or "bottle designs" in text.lower()
    # The related/more-from rail must be gone.
    assert "acme cola" not in text.lower()
    assert "fizzly" not in text.lower()


def test_related_only_page_is_dropped():
    # Headline has no term; body (after stripping) has no term -> not relevant.
    verdict = relevance.validate_relevance(
        "Beverage industry sees packaging changes this quarter", TERMS, PAGE_RELATED_ONLY
    )
    assert verdict["relevant"] is False


def test_body_match_page_is_kept_with_fetched_text():
    verdict = relevance.validate_relevance("Local drinks market update", TERMS, PAGE_BODY_MATCH)
    assert verdict["relevant"] is True
    assert verdict["matched_in"] == "body"
    assert "acme cola" in verdict["text"].lower()
    # Boilerplate (nav/footer/related) not carried into stored text.
    assert "copyright" not in verdict["text"].lower()


def test_headline_match_is_kept():
    verdict = relevance.validate_relevance("Acme Cola unveils new can", TERMS, None)
    assert verdict["relevant"] is True
    assert verdict["matched_in"] == "headline"


def test_no_html_no_headline_match_drops():
    verdict = relevance.validate_relevance("Unrelated headline about weather", TERMS, None)
    assert verdict["relevant"] is False
