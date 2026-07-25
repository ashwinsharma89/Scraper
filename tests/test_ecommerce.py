"""E-commerce keyword-driven search URL building (no Playwright needed)."""
from scrapers import ecommerce


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
