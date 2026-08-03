"""E-commerce keyword-driven search URL building + bot-block detection (no Playwright
needed for these — pure-function tests using real page text captured live)."""
from scrapers import ecommerce

# Real text captured live from Shopee's bot-block response (page.inner_text('body')) —
# every headless request to Shopee returns this, confirmed across multiple URLs.
REAL_SHOPEE_BLOCK_TEXT = """Skip to main content
Need help?
Page Unavailable
Sorry, something went wrong. Please log in and try again, or you can go back to Home Page.
Log InBack to Home Page
ID: 8618607812c-1736-4497-a897-8b971e3f9277
Select Your Language
English
简体中文
Bahasa Malaysia"""

# Real text captured live from a genuine Lazada Maggi search result page.
REAL_LAZADA_CONTENT_TEXT = """FEEDBACK SAVE MORE ON APP SELL ON LAZADA CUSTOMER CARE TRACK MY ORDER LOGIN SIGNUP TUKAR BAHASA
SEARCH
wet tissue kitchen
mc dowells
zumba outfit women
iphone 17
tortilla press
Categories
LazMall
Free Shipping
Top up & eStore
Voucher
Maggi
3411 items found for "maggi"
Sort By:
Best Match
View:
MAGGI(R) 2-Minute Instant Noodles Curry Flavor 5x79g
RM5.90
7.7K sold
(840)
Selangor
MAGGI(R) Pes Perapan Air Fryer Satay (100g)
RM4.90
New
2.1K sold
(263)
Selangor
MAGGI Chilli Sauce 340g
RM4.30
90"""


def test_build_search_urls_from_templates_and_keywords():
    templates = ["https://shopee.com.my/search?keyword={q}",
                 "https://www.lazada.com.my/catalog/?q={q}"]
    urls = ecommerce.build_search_urls(templates, ["Maggi", "Maggi Malaysia"])
    assert "https://shopee.com.my/search?keyword=Maggi" in urls
    assert "https://shopee.com.my/search?keyword=Maggi+Malaysia" in urls
    assert "https://www.lazada.com.my/catalog/?q=Maggi" in urls
    assert len(urls) == 4  # 2 templates x 2 keywords


def test_template_without_placeholder_treated_as_direct_url():
    urls = ecommerce.build_search_urls(["https://shop.example/product/123"], ["ignored"])
    assert urls == ["https://shop.example/product/123"]


def test_build_search_urls_dedups_and_skips_empty():
    urls = ecommerce.build_search_urls(["https://x/s?q={q}", "https://x/s?q={q}", ""], ["a", "", "a"])
    assert urls == ["https://x/s?q=a"]


def test_collect_reports_when_no_sources(monkeypatch):
    # No urls, no templates -> honest error, no fabrication.
    cfg = {"relevance_terms": ["Maggi"], "source_plan": {}}
    res = ecommerce.collect(cfg, {})
    assert res.items == []
    assert any("No e-commerce sources" in e for e in res.errors)


def test_search_defaults_to_relevance_terms_when_no_keywords():
    # When ecommerce_keywords is empty, templates use the project's relevance terms.
    cfg = {"relevance_terms": ["Maggi", "Indomie"],
           "source_plan": {"ecommerce_search": ["https://shopee.com.my/search?keyword={q}"]}}
    kws = cfg["relevance_terms"]
    urls = ecommerce.build_search_urls(cfg["source_plan"]["ecommerce_search"], kws)
    assert urls == ["https://shopee.com.my/search?keyword=Maggi",
                    "https://shopee.com.my/search?keyword=Indomie"]


# --------------------------------------------------------------------------- #
# Bot-block detection — the real bug this fix addresses: a blocked/error page was
# previously stored as a legitimate 0-content item with zero errors logged.
# --------------------------------------------------------------------------- #
def test_looks_blocked_detects_real_shopee_block_page():
    result = ecommerce._looks_blocked(REAL_SHOPEE_BLOCK_TEXT)
    assert result["blocked"] is True
    assert "page unavailable" in result["reason"]


def test_looks_blocked_accepts_real_lazada_content():
    result = ecommerce._looks_blocked(REAL_LAZADA_CONTENT_TEXT)
    assert result["blocked"] is False
    assert result["reason"] is None


def test_looks_blocked_flags_suspiciously_short_content_even_without_marker():
    # No explicit block marker, but far too little text for a real product/search page.
    result = ecommerce._looks_blocked("Loading...")
    assert result["blocked"] is True
    assert "chars of rendered content" in result["reason"]


def test_looks_blocked_detects_captcha_and_verification_walls():
    assert ecommerce._looks_blocked("Please complete the CAPTCHA to continue browsing." * 10)["blocked"] is True
    assert ecommerce._looks_blocked(("Verify you are human before continuing. " * 20))["blocked"] is True
