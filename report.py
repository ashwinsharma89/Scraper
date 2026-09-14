"""`/report/draft` — a Markdown five-pillar report skeleton.

Auto-fills measured-layer statistics (each with its n-size) and cited-layer entries
(each with its citation), and leaves explicit [ANALYST INPUT] markers wherever human
judgment is required. Trend sub-sections are generated from the project's configured
trend terms PLUS emergent themes found in analysis — never a hard-coded trend list.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import analytics
import storage
from version import __version__

MARKER = "[ANALYST INPUT]"


def _n(label: str, n: int) -> str:
    flag = "  ⚠️ _low-confidence (n<100)_" if n < analytics.LOW_CONFIDENCE_THRESHOLD else ""
    return f"(n={n}){flag}"


def draft_report(project_id: int) -> str:
    project = storage.get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    cfg = project["config"]
    market = cfg.get("market", {})
    product = cfg.get("product", {})

    dash = analytics.dashboard(project_id)
    by_channel = analytics.sentiment_by_channel(project_id)
    drivers = analytics.top_purchase_drivers(project_id)
    bvc = analytics.brand_vs_competitor_sentiment(project_id)
    trends = analytics.trend_volume_over_time(project_id)
    verbatims = analytics.top_verbatims_per_theme(project_id, per_theme=3)
    cited = storage.list_market_intel(project_id, entry_type="cited")

    lines: List[str] = []
    w = lines.append

    w(f"# Market & Product Intelligence — {product.get('brand', '(brand)')}")
    w(f"_Market: {market.get('country', '')} · Languages: {', '.join(market.get('languages', []))} · "
      f"Generated {datetime.now(timezone.utc).date().isoformat()} · MarketLens v{__version__}_")
    w("")
    w(f"> Draft skeleton. Measured stats carry their n-size; cited stats carry their source. "
      f"Fill every {MARKER} with analyst judgment before delivery.")
    w("")

    # -------------------------------------------------------------- Pillar 1
    w("## 1. Market Overview")
    w("")
    if cited:
        w("**Cited market data:**")
        for e in cited:
            src = f"{e.get('source_name', '?')}, {e.get('publication_date', 'n.d.')}"
            w(f"- **{e.get('metric') or e.get('category')}**: {e.get('value')} "
              f"— _{src}_ ([source]({e.get('source_url', '')})); confidence: {e.get('confidence')}")
    else:
        w(f"- {MARKER}: No cited market data entered yet. Add market size / CAGR / share via the "
          f"Market Intelligence (Cited) workspace.")
    w("")
    w(f"- Total signals collected across channels: **{dash['total_items']}** "
      f"({dash['total_stories']} unique stories" +
      (f", {round(dash['syndication_ratio']*100)}% syndicated/reprinted" if dash["syndication_ratio"] > 0 else "") +
      f"); analyzed: **{dash['total_analyzed']}**.")
    w(f"- {MARKER}: Synthesize the competitive landscape and market structure.")
    w("")

    # -------------------------------------------------------------- Pillar 2
    w("## 2. Consumer Intelligence")
    w("")
    w(f"- Overall net sentiment across analyzed signals: **{dash['overall_net_score']}** "
      f"{_n('overall', dash['total_analyzed'])}.")
    w("")
    w("**Sentiment by channel:**")
    for ch in by_channel:
        w(f"- {ch['channel']}: net **{ch['net_score']}** {_n(ch['channel'], ch['n'])} "
          f"· languages: {ch['language_breakdown']}")
    w("")
    w("**Brand vs. competitor sentiment:**")
    for row in bvc:
        w(f"- {row['brand_focus']}: net **{row['net_score']}** {_n(row['brand_focus'], row['n'])}")
    w("")
    w("**Top purchase drivers** " + _n("drivers", drivers["n"]) + ":")
    for d in drivers["drivers"][:10]:
        w(f"- {d['driver']} ({d['count']})")
    w("")
    w(f"- {MARKER}: Interpret what drives choice and how the brand is perceived vs. rivals.")
    w("")

    # -------------------------------------------------------------- Pillar 3
    w("## 3. Key Trends")
    w("")
    w("_Sub-sections below are generated from configured trend terms + emergent themes in the data._")
    w("")
    for s in trends["series"]:
        theme = s["trend_category"]
        w(f"### Trend: {theme} {_n(theme, s['n'])}")
        months = ", ".join(f"{m}:{c}" for m, c in list(s["by_month"].items())[-6:])
        if months:
            w(f"- Volume over recent months: {months}")
        # Attach up to 3 representative verbatims for this theme.
        theme_v = next((t for t in verbatims["themes"] if t["theme"] == theme), None)
        if theme_v:
            for v in theme_v["verbatims"]:
                if v.get("summary_en"):
                    w(f"  - _\"{v['summary_en']}\"_ ({v['sentiment']}, {v['source']})")
        w(f"- {MARKER}: Is this trend rising, and what does it mean for the brand?")
        w("")

    # -------------------------------------------------------------- Pillar 4
    w("## 4. Product Innovation")
    w("")
    w(f"- {MARKER}: Translate purchase drivers and complaints into product/packaging opportunities.")
    w("- Signals to mine: negative-sentiment verbatims and unmet-need themes above.")
    w("")

    # -------------------------------------------------------------- Pillar 5
    w("## 5. Partnership Opportunities")
    w("")
    manual_ads = storage.list_market_intel(project_id, entry_type="manual_ad")
    if manual_ads:
        w("**Observed advertisers/creatives (Manual Intelligence):**")
        for e in manual_ads[:15]:
            w(f"- {e.get('source_name')}: {e.get('value')} — {e.get('extra', {}).get('creative_theme', '')}")
    else:
        w(f"- {MARKER}: No manual ad observations recorded yet.")
    w(f"- {MARKER}: Identify retail, channel, and co-marketing partnership angles.")
    w("")

    w("---")
    w("### Methodology & honesty notes")
    w(f"- Model-generated tags: ~85–95% human agreement — spot-check before quoting.")
    w(f"- Digital sources skew urban/online/literate-in-covered-languages — not the whole market.")
    w(f"- Tier-3 platforms (Instagram, Facebook, LinkedIn, WhatsApp, TikTok organic, app-only "
      f"delivery) are NOT covered; see the export Methodology tab.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# File outputs (Markdown + Word + PDF)
# --------------------------------------------------------------------------- #
def _out_path(project_id: int, ext: str) -> str:
    from pathlib import Path

    from settings import settings

    settings.ensure_dirs()
    project = storage.get_project(project_id)
    safe = "".join(c for c in (project["name"] if project else "project") if c.isalnum() or c in "-_") or "project"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return str(Path(settings.exports_dir) / f"MarketLens_Report_{safe}_{ts}.{ext}")


def save_markdown(project_id: int, out_path: str = None) -> str:
    md = draft_report(project_id)
    path = out_path or _out_path(project_id, "md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    storage.audit("report.export.md", "report draft downloaded (markdown)", project_id=project_id)
    return path


def save_docx(project_id: int, out_path: str = None) -> str:
    """Render the Markdown report into a styled .docx (Word) file.

    A lightweight line-based Markdown converter handles the report's structure
    (headings, bullets, block-quotes, horizontal rules, bold). python-docx is
    imported lazily so the rest of the tool never requires it.
    """
    from docx import Document
    from docx.shared import Pt, RGBColor

    md = draft_report(project_id)
    path = out_path or _out_path(project_id, "docx")

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    def _add_runs(paragraph, text):
        # Minimal **bold** handling; everything else is plain text.
        parts = text.split("**")
        for i, part in enumerate(parts):
            if not part:
                continue
            run = paragraph.add_run(part)
            run.bold = (i % 2 == 1)

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            h = doc.add_heading(line[2:], level=1)
        elif line.strip() == "---":
            doc.add_paragraph().add_run("_" * 40)
        elif line.lstrip().startswith(("- ", "* ")):
            indent = len(line) - len(line.lstrip())
            p = doc.add_paragraph(style="List Bullet")
            if indent >= 2:
                p.paragraph_format.left_indent = Pt(18)
            _add_runs(p, line.lstrip()[2:])
        elif line.startswith(">"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(18)
            r = p.add_run(line.lstrip("> ").strip())
            r.italic = True
        else:
            p = doc.add_paragraph()
            _add_runs(p, line)

    doc.save(path)
    storage.audit("report.export.docx", "report draft downloaded (Word)", project_id=project_id)
    return path


def _md_inline_to_html(text: str) -> str:
    """Escape HTML-special characters, then restore **bold** as <b> tags. Escaping
    first is safe here because escape() never touches literal asterisks."""
    import html as _html

    escaped = _html.escape(text)
    parts = escaped.split("**")
    return "".join(f"<b>{p}</b>" if i % 2 == 1 else p for i, p in enumerate(parts))


def _markdown_to_simple_html(md: str) -> str:
    """Convert the report's Markdown into the small HTML subset fpdf2's write_html()
    understands (h1-h3, p, ul/li, b, hr). Deliberately minimal, not a general Markdown
    parser — draft_report() only ever emits #/##/### headings, "- "/"* " bullets, "> "
    block-quotes, "---" rules, **bold**, and plain lines (confirmed by inspection); a
    general parser would be needless weight for a fixed, known output shape."""
    out: List[str] = []
    in_list = False

    def _close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            _close_list()
            continue
        if line.startswith("### "):
            _close_list()
            out.append(f"<h3>{_md_inline_to_html(line[4:])}</h3>")
        elif line.startswith("## "):
            _close_list()
            out.append(f"<h2>{_md_inline_to_html(line[3:])}</h2>")
        elif line.startswith("# "):
            _close_list()
            out.append(f"<h1>{_md_inline_to_html(line[2:])}</h1>")
        elif line.strip() == "---":
            _close_list()
            out.append("<hr>")
        elif line.lstrip().startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_md_inline_to_html(line.lstrip()[2:])}</li>")
        elif line.startswith(">"):
            _close_list()
            out.append(f"<p><i>{_md_inline_to_html(line.lstrip('> ').strip())}</i></p>")
        else:
            _close_list()
            out.append(f"<p>{_md_inline_to_html(line)}</p>")
    _close_list()
    return "\n".join(out)


def save_pdf(project_id: int, out_path: str = None) -> str:
    """Render the Markdown report into a PDF file, via the small Markdown->HTML
    subset above + fpdf2's built-in write_html(). fpdf2 is pure Python (no system
    libraries like a Cairo/Pango stack that a heavier HTML-to-PDF renderer would
    need) and imported lazily here, matching every other optional export dependency
    in this module (python-docx) and the rest of the tool's convention.

    Uses a bundled DejaVu Sans (fonts/, Bitstream Vera license — see
    fonts/DEJAVU_LICENSE.txt — free to embed/redistribute) instead of fpdf2's default
    core "Helvetica" font: the core fonts only support latin-1/cp1252 and crash on
    genuinely common report characters (an em dash in the title line, ⚠️ in the
    low-confidence flag, an accented brand name like "Nescafé" — found live, this
    crashed the very first real export attempt). DejaVu Sans doesn't cover every
    script (no Devanagari/Tamil/Telugu/CJK glyphs) — an honest, accepted scope limit,
    not a silent gap: draft_report() itself only ever emits English text plus
    Latin-Extended names (every native-script field is deliberately summary_en'd or
    dropped before it reaches the report — see analytics.top_verbatims_per_theme()'s
    "text" field, which report.py never renders — so this covers everything the
    report actually produces)."""
    from pathlib import Path

    from fpdf import FPDF

    md = draft_report(project_id)
    path = out_path or _out_path(project_id, "pdf")
    html = _markdown_to_simple_html(md)

    font_dir = Path(__file__).parent / "fonts"
    pdf = FPDF(format="A4")
    # Uncompressed content streams: a few KB bigger, but keeps the PDF's own text
    # bytes greppable (directly, no PDF-parsing library) for both debugging and this
    # module's own tests, and the report is small — the size trade-off is a non-issue.
    pdf.set_compression(False)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(font_dir / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(font_dir / "DejaVuSans-Bold.ttf"))
    pdf.add_font("DejaVu", "I", str(font_dir / "DejaVuSans-Oblique.ttf"))
    pdf.add_font("DejaVu", "BI", str(font_dir / "DejaVuSans-BoldOblique.ttf"))
    pdf.set_font("DejaVu", size=11)
    pdf.write_html(html)
    pdf.output(path)

    storage.audit("report.export.pdf", "report draft downloaded (PDF)", project_id=project_id)
    return path
