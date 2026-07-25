# MarketLens

**Enterprise-grade, local-first market & product intelligence.** Run Market Analysis and
Product Analysis studies on *any* product in *any* market. Nothing in the codebase is
hard-coded to a brand, category, country, or language — every project-specific value
flows from a project configuration created by the intake wizard.

## Three non-negotiable principles

1. **Decision-grade data.** Nothing lives only in memory. Every collected item has full
   lineage to the run that produced it. Counts are never inflated by duplicates. Every
   export documents its own methodology **and** its gaps.
2. **Honest feasibility.** We do not build fake or fragile scrapers for platforms that
   block automation (Instagram, Facebook, LinkedIn, WhatsApp, TikTok organic, app-only
   delivery). Those are **documented gaps** with manual-research workflows. We never
   simulate or fabricate data, and every failure is surfaced.
3. **Precision over volume.** A keyword in a page's related-links footer is *not* a
   relevant result. Content validation is mandatory (see `scrapers/relevance.py`).

---

## Quick start

You need either **Docker** (recommended — includes the browser for e-commerce scraping)
or **Python 3.11+**.

### Path A — Docker (primary sharing path)

```bash
# 1. Get the repo (or just docker-compose.yml + the image)
# 2. From the project directory:
docker compose up
# 3. Open http://localhost:8000
```

Data persists in the named volume `marketlens_data`. To add API keys or switch to team
mode, copy `.env.example` to `.env`, fill it in, and re-run `docker compose up`.

### Path B — Python (no Docker)

**macOS / Linux**
```bash
./setup.sh
source .venv/bin/activate
python app.py
# open http://localhost:8000
```

**Windows**
```bat
setup.bat
.venv\Scripts\activate.bat
python app.py
REM open http://localhost:8000
```

`setup.sh` / `setup.bat` create a venv, install dependencies, install the Playwright
Chromium browser, and copy `.env.example` to `.env`.

### Create the demo study

```bash
python seed_demo.py     # creates "Acme Cola (demo)" in market "Singapore"
```

The demo is an **obviously fictional** brand created *through the wizard* purely to prove
the flow. It contains **no fabricated collected data** — the study starts empty; you run
real collection to populate it. There are **no real-brand defaults anywhere in the code.**

---

## The intake wizard (the generalization mechanism)

Creating a study collects: **market** (country + target languages), **product** (brand,
parent company, category + type), **competitors**, **keywords** (core, native-language
per language, trend/issue terms), and **relevance terms** (auto-derived as
brand + competitors + category, user-editable).

The wizard then generates a **source plan** adapted to the market + category:

- Google News search-feed URLs built from keywords × languages with the correct
  `hl`/`gl`/`ceid` for the chosen country.
- GDELT `sourcecountry` code.
- Suggested subreddit candidates (country + category patterns, user-confirmable).
- Segment applicability switches (delivery/quick-commerce enabled only for applicable
  categories; B2B surfaces trade-press guidance instead of consumer commerce).
- Empty slots you fill from local knowledge: e-commerce URLs, forum URLs, direct RSS
  feeds (the **feed-health check** validates each and reports dead feeds).

**AI source discovery** (Source plan → "✨ Suggest sources"): given the project's market +
category + brand, Claude proposes real candidate sources per channel (news RSS, e-commerce
search URLs, forums, subreddits, quick-commerce), then the tool **validates every one** —
RSS via the feed-health check (with homepage autodiscovery when a feed path is guessed
wrong), web URLs via a reachability probe — and shows each with a ✓/✗ status. You confirm
which to add; nothing dead or fabricated is auto-added, and app-only platforms are surfaced
as Tier-3 gaps, not scrapers. Requires `ANTHROPIC_API_KEY`.

**Market filter** (news): items are kept only if there's a signal they're in-market — the
outlet's domain ends in the country ccTLD (e.g. `.my`) or a market term appears — so a
Malaysia study isn't flooded with e.g. Indian coverage. On by default; toggle on the
Collect tab, edit market terms (add cities/regions) in Source plan.

All wizard output is **editable config**, stored in the DB, and exportable as YAML
(`config.yaml ↗` on the Overview tab). Multiple projects are supported; every
run/item/analysis row carries `project_id`, and switching projects switches all defaults.

---

## Collection channels

### Tier 1 — automated scrapers (built fully)

| Channel | Method | Key limitation |
|---|---|---|
| **E-commerce** (Playwright) | Rendered product/category/search pages; review text; image URLs; intercepts internal review XHR where detectable; per-URL proxy. | ToS gray zone — internal research, low volume, read-only; proxy recommended beyond light use. **Snapshot only, no backfill.** |
| **News / RSS** | Regular RSS + Google News search feeds; monthly/weekly date chunking to beat the ~100-result cap; OR keyword filter; strict body-content relevance validation; Google News redirect resolution; per-feed health check. | Regular RSS can't reach back in time; only chunked Google News and GDELT can. |
| **GDELT** (DOC 2.0) | `sourcecountry` from config; monthly chunking, 250/chunk. | **Metadata only** (title/link/date/outlet/language) — no article body. |
| **Reddit** (public JSON) | Configured subreddits; multi-sort union (new/top/relevance/comments); nested comments for top-N posts; deleted/removed excluded; graceful 429 handling. | Public JSON only, no key. |
| **Forums** (requests + BS4) | User URLs; auto/CSS post containers; multi-language next-page pagination; page cap. | Structure varies; custom CSS selector may be needed. |
| **YouTube** (Data API v3) | Search by regionCode/relevanceLanguage + date window; full comment threads; quota-aware. | Requires API key. |
| **Google Trends** (pytrends) | Interest-over-time + related queries for config keywords, geo from config. | Relative index, not absolute volume. |
| **Google Business** (Places API) | Place search + reviews for the brand's retail/service presence. | Requires API key; capped review sample. |
| **Quora** (best-effort) | Question-page scraping with the same strict validation. | Frequently blocks automation; logged honestly. |
| **Image analysis** | EXIF (Pillow) + Claude-vision reading of packaging/labels/claims/prices on collected product images. | Runs only on images collected by the e-commerce channel. |

Scrape jobs run **one at a time** through a single-writer queue (Collect tab shows job
status), so concurrent triggers never corrupt state.

### Tier 2 — assisted-manual workflows (Manual intel tab)

Meta Ad Library, TikTok Creative Center / Ads Library, Google Ads Transparency Center,
and Twitter/X are free to browse but hostile to automation. MarketLens generates a
per-platform **checklist with deep links** pre-built from your brand/competitor names,
and a structured entry form (advertiser, platform, creative theme, format, first-seen
date, screenshot upload, notes) saved with attribution. Twitter/X has an optional
third-party API-key slot.

### Tier 3 — documented gaps (never scraped)

Instagram, Facebook pages/groups, LinkedIn, WhatsApp, TikTok organic, and app-only
delivery/quick-commerce are **not covered**, with the reason listed on the Manual intel
tab and in **every export's Methodology tab**. Manual-entry only.

---

## Market Intelligence (the cited layer)

A structured desk-research workspace for market size/CAGR, competitor share, GDP and
category share, demographics, economic sentiment, regulation, and entry barriers. **Every
entry requires** value, source name, source URL, publication date, accessed date, and a
confidence rating — citation discipline is enforced by the tool. No paywalled research is
auto-scraped; this layer is human-entered.

## Analysis

`/analyze` batches unanalyzed items (12/batch) to the Claude API (model configurable,
default `claude-haiku-4-5`). Claude reads all project languages natively; the one-line
English summary is the translation layer. Per-item tags: sentiment, language, summary,
rating signal, purchase driver, usage occasion, trend category (seeded from your trend
terms + "other/emergent"), brand focus, promo mentioned, emotion. Analysis is
**idempotent** and failed batches are retryable. The Analysis tab shows a live
sentiment×channel dashboard; every aggregate carries its **n-size**.

## Export & report

- **Excel workbook** (Export tab): Summary · Methodology · Confidence · Representativeness
  · Analysis Summary · Market Intelligence (Cited) · Run Log · one data tab per channel.
  Any headline stat resting on **< 100 items or a single segment** is auto-flagged
  "emerging / low-confidence". The tool version is stamped into the workbook. Optional
  published-date filter.
- **Report draft** (`/report/draft`): a Markdown five-pillar skeleton — Market Overview,
  Consumer Intelligence, Key Trends, Product Innovation, Partnership Opportunities —
  auto-filling measured stats (with n-sizes) and cited entries (with citations), leaving
  `[ANALYST INPUT]` markers for judgment. Trend sub-sections come from your configured
  trend terms + emergent themes — never a hard-coded list.

## Scheduler

Cron-like recurring runs (e.g. a weekly e-commerce price/review wave, a daily news pull)
stored in the DB and executed by a background loop, producing normal audited runs. Manage
per project on the Schedules tab.

---

## API keys

All secrets come from the environment (or `.env`) **only** — never committed, never stored
in the DB in plaintext. Each key's channel is simply skipped (with an honest log line) if
its key is unset.

| Variable | Used by | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Analysis + image vision | https://console.anthropic.com → API Keys |
| `YOUTUBE_API_KEY` | YouTube channel | Google Cloud Console → enable *YouTube Data API v3* → create API key |
| `GOOGLE_PLACES_API_KEY` | Google Business channel | Google Cloud Console → enable *Places API* → create API key |
| `TWITTER_API_KEY` | Twitter/X manual intel (optional) | Your third-party X API provider |

Set `ANALYSIS_MODEL` / `VISION_MODEL` to override the default Claude model.

---

## Team-mode deployment (shared LAN / VPS)

```bash
MODE=team \
ADMIN_USER=admin \
ADMIN_PASSWORD='choose-a-strong-password' \
SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')" \
ANTHROPIC_API_KEY=... \
python app.py           # binds 0.0.0.0:8000, login required
```

Or with Docker: put those in `.env` and `MODE=team docker compose up`.

- **Auth** is deliberately simple: a users table (username + salted PBKDF2 hash), a signed
  session cookie, and an admin bootstrapped on first boot from the env vars above. No OAuth.
- **Attribution**: manual-intel entries, cited entries, purges, schedule changes, and every
  scrape run record the acting user. The Run Log shows who did what.
- **Concurrency**: SQLite WAL + a single-writer job queue — scrape jobs run sequentially,
  and User B sees User A's running job via the job-status endpoint instead of a frozen button.

Create additional users via `POST /api/auth/users` (admin only) while signed in.

## Portability of work

- **Project archive** (Export tab → "Export project archive `.mlz`"): bundles config +
  items + analysis + market intel + run log into one file that imports cleanly onto another
  instance (`POST /api/archive/import`). Studies move between a laptop and a team server.
- The **Excel export** remains the client-facing artifact; the archive is the working-data
  transfer format.

## Versioning & updates

- The semantic version shows in the UI footer and is stamped into every Excel export, so any
  report is traceable to the build that produced it.
- Schema migrations run automatically and idempotently on startup (`migrations.py`).
  Upgrading never requires wiping data.

---

## Operational honesty (please read)

- **E-commerce scraping is a ToS gray zone** — keep it internal, low-volume, read-only; use
  a proxy beyond light use.
- **Marketplace reviews are snapshots** — the time series starts when scheduled scraping
  starts; there is no backfill.
- **Regular RSS cannot reach back in time** — only chunked Google News and GDELT can.
- **Never trust Tier-3 coverage** — MarketLens does not scrape those platforms and never
  fabricates data for a failed scrape.

## Testing

All network is mocked; tests never hit the internet.

```bash
python -m pytest -q
```

Coverage includes: cross-run dedup never inflates; lineage recorded; project isolation
(same content hash, two projects, both stored); date-chunk continuity; strict relevance
(drops related-links-only matches, keeps body matches with fetched text); multi-keyword OR
filter; wizard Google News URL generation for arbitrary (country, language, keyword);
Reddit comment-tree excludes deleted; export has all required tabs; analysis idempotency;
feed health flags a dead feed; archive export→import round-trips losslessly on a fresh DB;
team-mode endpoints reject unauthenticated requests while solo allows them; schema
migrations apply cleanly to a previous-version DB.

## Architecture

Python 3.11+, FastAPI, SQLite (WAL). Single-page vanilla-JS frontend in `/static` (no build
step). No hard-coded absolute paths; the data directory is set by `MARKETLENS_DATA_DIR`
(default `./data`).

| Module | Responsibility |
|---|---|
| `app.py` | FastAPI routes + static SPA |
| `config.py` | Projects + intake wizard + source-plan generation + feed health |
| `storage.py` | Persistence, lineage, cross-run dedup, project isolation |
| `migrations.py` | Idempotent versioned schema migrations |
| `http_client.py` | One retrying session, per-domain rate limiting |
| `jobs.py` | Single-writer job queue + the collection runner |
| `scrapers/` | One module per channel + `relevance.py` (strict validation) |
| `analysis.py` / `analytics.py` | LLM tagging + aggregations (with n-sizes) |
| `market_intel.py` | Cited layer + Manual Intelligence |
| `export.py` / `report.py` | Excel workbook + Markdown five-pillar draft |
| `auth.py` | Team-mode auth (hashing, sessions, admin bootstrap) |
| `archive.py` | Project export/import (`.mlz`) |
| `scheduler.py` | Background recurring-run loop |
| `tests/` | pytest suite (network mocked) |
```
