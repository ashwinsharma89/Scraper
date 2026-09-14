"""Export workbook contains all required tabs + version stamp; report scaffold; citations."""
import json

import analysis
import config
import export
import market_intel
import report
import storage
from version import __version__

REQUIRED_TABS = ["Summary", "Methodology", "Confidence", "Representativeness",
                 "Analysis Summary", "Market Intelligence (Cited)", "Run Log"]


def _cfg():
    import config
    return config.run_wizard({
        "market": {"country": "Singapore", "languages": ["en"]},
        "product": {"brand": "Acme Cola", "category": "cola", "category_type": "fmcg_food"},
        "competitors": ["Fizzly"],
        "keywords": {"trend_terms": ["sugar-free"]},
    })


def _seed_and_analyze(pid):
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        {"title": "Acme Cola review", "text": "tasty and cheap", "link": "http://a", "published": "2024-03-01"},
        {"title": "Fizzly launch", "text": "new competitor drink", "link": "http://b", "published": "2024-03-02"},
    ])

    def call(prompt, model):
        import json
        n = prompt.count("] source=")
        return json.dumps([{
            "sentiment": "positive", "sentiment_score": 0.6, "language": "en",
            "summary_en": "positive review", "purchase_driver": "price",
            "trend_category": "sugar-free", "brand_focus": "target brand",
            "promo_mentioned": False, "emotion": "joy",
        } for _ in range(n)])

    analysis.analyze_all(pid, call_fn=call, model="test-model")


def test_workbook_has_all_required_tabs_and_version(fresh_db, tmp_path):
    from openpyxl import load_workbook

    pid = storage.create_project("Acme Study", _cfg())
    _seed_and_analyze(pid)
    market_intel.add_cited_entry(pid, {
        "category": "Market size", "metric": "SG cola market", "value": "S$500m",
        "source_name": "Statista", "source_url": "http://statista.example",
        "publication_date": "2024-01-01", "accessed_date": "2024-06-01", "confidence": "medium",
    }, entered_by="alice")

    path = tmp_path / "out.xlsx"
    export.build_workbook(pid, out_path=str(path))
    wb = load_workbook(str(path))

    for tab in REQUIRED_TABS:
        assert tab in wb.sheetnames, f"missing tab: {tab}"
    # One data tab per channel that has items.
    assert "news" in wb.sheetnames
    # Combined master tab with the full column set.
    assert "All Items" in wb.sheetnames
    # Row 1 is the tab's own per-tab description (HANDOFF §7, self-documenting tabs);
    # the real column headers are row 2.
    assert wb["All Items"]["A1"].value  # a non-empty description was actually written
    headers = [c.value for c in wb["All Items"][2]]
    assert headers == ["id", "source", "title", "text", "link", "published", "run_id",
                       "story_group_size", "sentiment", "sentiment_score", "language",
                       "summary_en", "rating_signal", "purchase_driver", "usage_occasion",
                       "trend_category", "brand_focus", "promo_mentioned", "emotion"]
    # Version stamped into the Summary tab.
    summary_vals = [c.value for row in wb["Summary"].iter_rows() for c in row if c.value]
    assert any(f"v{__version__}" in str(v) for v in summary_vals)
    # Cited citation present.
    cited_vals = [c.value for row in wb["Market Intelligence (Cited)"].iter_rows() for c in row]
    assert "http://statista.example" in cited_vals


def test_export_surfaces_syndication_not_just_raw_count(fresh_db, tmp_path):
    from openpyxl import load_workbook

    pid = storage.create_project("Syndication Test", _cfg())
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        {"title": "Maggi price rises in KL - NST", "text": "x", "link": "http://a", "published": "2026-03-01"},
        {"title": "Maggi price rises in KL - Star", "text": "x", "link": "http://b", "published": "2026-03-01"},
        {"title": "Unrelated Maggi story", "text": "y", "link": "http://c", "published": "2026-03-20"},
    ])

    def call(prompt, model):
        import json
        n = prompt.count("] source=")
        return json.dumps([{"sentiment": "positive", "sentiment_score": 0.5, "language": "en",
                           "summary_en": "s", "purchase_driver": "price", "trend_category": "x",
                           "brand_focus": "target brand", "promo_mentioned": False,
                           "emotion": "joy"} for _ in range(n)])

    analysis.analyze_all(pid, call_fn=call, model="test-model")
    path = tmp_path / "syn.xlsx"
    export.build_workbook(pid, out_path=str(path))
    wb = load_workbook(str(path))

    # Summary tab states unique-stories distinctly from raw item count.
    summary_pairs = [(r[0].value, r[1].value) for r in wb["Summary"].iter_rows() if r[0].value]
    d = dict(summary_pairs)
    assert d.get("Total items collected") == 3
    assert d.get("Unique stories (syndication-adjusted)") == 2

    # Data tab carries a story_group_size column reflecting the reprint. Row 1 is the
    # tab's own description; real headers are row 2, data from row 3.
    ws = wb["All Items"]
    headers = [c.value for c in ws[2]]
    idx = headers.index("story_group_size")
    sizes = sorted(row[idx] for row in ws.iter_rows(min_row=3, values_only=True))
    assert sizes == [1, 2, 2]  # two reprints (size 2 each) + one standalone (size 1)


def test_export_exclude_unrelated_drops_only_unrelated_rows_from_raw_tabs(fresh_db, tmp_path):
    """HANDOFF §7 "target brand only" export filter: brand_focus='unrelated' rows are
    everywhere else (analytics.py's headline stats) already excluded by default —
    until this flag, the raw All Items/per-channel tabs never matched that, so a
    client pivoting directly off the raw tab would see numbers analytics doesn't."""
    from openpyxl import load_workbook

    pid = storage.create_project("Filter Test", _cfg())
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        {"title": "Acme Cola review", "text": "tasty", "link": "http://a", "published": "2026-01-01"},
        {"title": "Unrelated weather story", "text": "rain today", "link": "http://b", "published": "2026-01-02"},
    ])

    def call(prompt, model):
        import json
        # Route by title so each item gets its real, distinct brand_focus tag.
        return json.dumps([
            {"sentiment": "positive", "sentiment_score": 0.5, "language": "en", "summary_en": "s",
             "purchase_driver": "price", "trend_category": "x", "brand_focus": "target brand",
             "promo_mentioned": False, "emotion": "joy"},
            {"sentiment": "neutral", "sentiment_score": 0.0, "language": "en", "summary_en": "s",
             "purchase_driver": "", "trend_category": "", "brand_focus": "unrelated",
             "promo_mentioned": False, "emotion": "neutral"},
        ])

    analysis.analyze_all(pid, call_fn=call, model="test-model")

    # Row 1 is the tab's own description, row 2 the real headers, data from row 3.
    unfiltered = tmp_path / "unfiltered.xlsx"
    export.build_workbook(pid, out_path=str(unfiltered))
    wb = load_workbook(str(unfiltered))
    assert wb["All Items"].max_row == 4  # description + header + 2 items -- unrelated included by default

    filtered = tmp_path / "filtered.xlsx"
    export.build_workbook(pid, exclude_unrelated=True, out_path=str(filtered))
    wb2 = load_workbook(str(filtered))
    assert wb2["All Items"].max_row == 3  # description + header + 1 item -- unrelated dropped
    titles = [row[2] for row in wb2["All Items"].iter_rows(min_row=3, values_only=True)]
    assert titles == ["Acme Cola review"]
    # Per-channel tab (only "news" here) gets the same filter.
    assert wb2["news"].max_row == 3

    # Summary tab documents the choice honestly, in both directions.
    def _summary_dict(wb):
        return dict((r[0].value, r[1].value) for r in wb["Summary"].iter_rows() if r[0].value)

    assert "None" in _summary_dict(wb)["Raw data tabs filter"]
    assert "Target brand only" in _summary_dict(wb2)["Raw data tabs filter"]


def test_confidence_tab_reports_the_news_engine_split(fresh_db, tmp_path):
    """HANDOFF §7: surface the Bing/Google split -- until now the Confidence tab never
    reported it at all (it wasn't computed anywhere in analytics.py), despite HANDOFF
    describing it as already there."""
    from openpyxl import load_workbook

    pid = storage.create_project("Engine Split Test", _cfg())
    run_id = storage.start_run(pid, "news", {})
    storage.save_items(pid, run_id, "news", [
        {"title": "a", "text": "x", "link": "http://x/a", "extra": {"engine": "google_news"}},
        {"title": "b", "text": "x", "link": "http://x/b", "extra": {"engine": "bing_news"}},
    ])
    path = tmp_path / "engine.xlsx"
    export.build_workbook(pid, out_path=str(path))
    wb = load_workbook(str(path))
    notes = [c.value for row in wb["Confidence"].iter_rows() for c in row if c.value]
    assert any("News engine split" in n and "1 via Google News" in n and "1 via Bing News" in n
              for n in notes)


def test_data_tabs_carry_a_self_documenting_description_row(fresh_db, tmp_path):
    """HANDOFF §7: "per-tab description headers in the Excel (self-documenting)" -- a
    raw data tab opened on its own (detached from Methodology, e.g. forwarded as a
    single sheet) must still say what it is and, for a per-channel tab, what that
    channel's real method/limitation is -- reusing CHANNEL_INFO (the SAME text the
    Collect tab UI shows) rather than a second, driftable copy of it."""
    from openpyxl import load_workbook

    pid = storage.create_project("Desc Test", _cfg())
    _seed_and_analyze(pid)
    path = tmp_path / "desc.xlsx"
    export.build_workbook(pid, out_path=str(path))
    wb = load_workbook(str(path))

    all_desc = wb["All Items"]["A1"].value
    assert "story_group_size" in all_desc  # explains the one column that isn't self-evident

    news_desc = wb["news"]["A1"].value
    from scrapers import CHANNEL_INFO
    assert CHANNEL_INFO["news"]["method"] in news_desc
    assert CHANNEL_INFO["news"]["limitation"] in news_desc


def test_cited_entry_requires_full_citation(fresh_db):
    pid = storage.create_project("P", _cfg())
    try:
        market_intel.add_cited_entry(pid, {"category": "Market size", "value": "x"})
        assert False, "should have raised"
    except ValueError as e:
        msg = str(e)
        assert "source_name" in msg and "source_url" in msg and "accessed_date" in msg


def test_report_draft_has_five_pillars_and_markers(fresh_db):
    pid = storage.create_project("P", _cfg())
    _seed_and_analyze(pid)
    md = report.draft_report(pid)
    for pillar in ["Market Overview", "Consumer Intelligence", "Key Trends",
                   "Product Innovation", "Partnership Opportunities"]:
        assert pillar in md
    assert "[ANALYST INPUT]" in md
    # Trend sub-section generated from configured trend term.
    assert "sugar-free" in md
    # n-sizes present.
    assert "n=" in md


def test_report_downloads_md_and_docx(fresh_db, tmp_path):
    pid = storage.create_project("P", _cfg())
    _seed_and_analyze(pid)

    md_path = report.save_markdown(pid, out_path=str(tmp_path / "r.md"))
    text = open(md_path, encoding="utf-8").read()
    assert "Market Overview" in text and "Consumer Intelligence" in text

    docx_path = report.save_docx(pid, out_path=str(tmp_path / "r.docx"))
    from docx import Document
    doc = Document(docx_path)
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert any("Consumer Intelligence" in h for h in headings)
    assert any("Key Trends" in h for h in headings)

    pdf_path = report.save_pdf(pid, out_path=str(tmp_path / "r.pdf"))
    raw = open(pdf_path, "rb").read()
    assert raw.startswith(b"%PDF-")
    # fpdf2's write_html() turns h2/h3 headings into real PDF outline/bookmark
    # entries, stored as literal readable /Title strings -- that's what these three
    # match against (body text is glyph-index-encoded via the embedded TTF font and
    # isn't byte-searchable this way; see test_save_pdf_handles_real_unicode_report_
    # content's comment for why that's not chased further here).
    assert b"Consumer Intelligence" in raw
    assert b"Key Trends" in raw
    assert b"Product Innovation" in raw


def test_save_pdf_handles_real_unicode_report_content(fresh_db, tmp_path):
    """Real bug found live building this feature: fpdf2's default core "Helvetica"
    font only supports latin-1/cp1252 and hard-crashes (FPDFUnicodeEncodingException)
    on the very first real export -- the report's OWN title line always contains an
    em dash ("# ... — {brand}"), and an accented brand name (e.g. "Nescafé", a real
    brand named in HANDOFF.md's own live-tested example) would hit the same wall.
    Fixed by embedding DejaVu Sans (fonts/) instead of the core font."""
    cfg = config.run_wizard({
        "market": {"country": "India", "languages": ["en"]},
        "product": {"brand": "Nescafé", "category": "coffee", "category_type": "fmcg_food"},
    })
    pid = storage.create_project("Unicode Brand Test", cfg)
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        {"title": "Nescafé review", "text": "tasty", "link": "http://a", "published": "2026-01-01"},
    ])

    def call(prompt, model):
        return json.dumps([{"sentiment": "positive", "sentiment_score": 0.5, "language": "en",
                           "summary_en": "s", "purchase_driver": "price", "trend_category": "x",
                           "brand_focus": "target brand", "promo_mentioned": False, "emotion": "joy"}])

    analysis.analyze_all(pid, call_fn=call, model="test-model")

    # The real bug: this used to raise FPDFUnicodeEncodingException before save_pdf()
    # switched off the core "Helvetica" font (latin-1/cp1252 only) to embedded DejaVu
    # Sans -- both the title line's em dash and "Nescafé"'s accented é would crash it.
    # fpdf2 encodes embedded-TTF body text as glyph indices (Identity-H), not literal
    # bytes, so byte-searching the PDF for "Nescafé" itself isn't meaningful without a
    # real PDF-parsing dependency (deliberately not added for this) -- completing
    # without raising, with real page content, IS the actual regression being guarded.
    pdf_path = report.save_pdf(pid, out_path=str(tmp_path / "unicode.pdf"))
    raw = open(pdf_path, "rb").read()
    assert raw.startswith(b"%PDF-")
    assert len(raw) > 2000  # a genuinely rendered page, not a near-empty stub


def test_markdown_to_simple_html_handles_every_construct_draft_report_emits(fresh_db):
    """The converter is deliberately NOT a general Markdown parser -- this pins down
    exactly the fixed set of constructs draft_report() actually produces, so a future
    change to draft_report()'s formatting fails loudly here instead of silently
    rendering wrong in the PDF."""
    md = "\n".join([
        "# Title Here",
        "_subtitle line_",
        "",
        "## 1. Section",
        "- bullet **bold** one",
        "- bullet two",
        "",
        "### Sub-heading (n=5)",
        "> a block-quote note",
        "---",
        "plain paragraph",
    ])
    html = report._markdown_to_simple_html(md)
    assert "<h1>Title Here</h1>" in html
    assert "<h2>1. Section</h2>" in html
    assert "<ul>" in html and "</ul>" in html
    assert "<li>bullet <b>bold</b> one</li>" in html
    assert "<h3>Sub-heading (n=5)</h3>" in html
    assert "<p><i>a block-quote note</i></p>" in html
    assert "<hr>" in html
    assert "<p>plain paragraph</p>" in html


def test_markdown_to_simple_html_escapes_special_characters():
    """A brand/competitor name containing '<', '>', or '&' must not corrupt the HTML
    fpdf2 parses -- e.g. a real "R&D" or "A vs. B < C" mention in generated text."""
    html = report._markdown_to_simple_html("Acme <Cola> & Fizzly < 5")
    assert "&lt;Cola&gt;" in html
    assert "&amp;" in html
    assert "<Cola>" not in html  # never a literal unescaped tag-looking string


def test_manual_intelligence_plan_deep_links(fresh_db):
    cfg = _cfg()
    plan = market_intel.manual_intelligence_plan(cfg)
    meta = next(p for p in plan if p["key"] == "meta_ad_library")
    # Deep links built for brand + competitor.
    names = [dl["name"] for dl in meta["deep_links"]]
    assert "Acme Cola" in names and "Fizzly" in names
    assert all("facebook.com/ads/library" in dl["url"] for dl in meta["deep_links"])
