# MarketLens — Handoff / Continuation Guide

You are taking over an in-progress build of **MarketLens**, a local-first market & product
intelligence tool. This document is everything you need to continue without re-deriving
context. Read `README.md` for the product overview; this file is the *engineering* handoff.

---

## 0. Ground rules (do not violate — they are the product's identity)

1. **Never fabricate or simulate data.** If a scrape/analysis fails, surface the error
   honestly and store nothing. Every item traces to the run that produced it.
2. **No hard-coding** of any brand, product, category, country, or language. Everything
   project-specific comes from the intake wizard / config. (Reference tables of *country
   codes* and *per-language UI labels* are fine — brands/outlets are not.)
3. **All network is mocked in tests.** Run the suite after every change.
4. **Secrets from environment only** (`.env`), never committed, never stored in the DB in
   plaintext.
5. After any local run that writes data, **reset to the pristine demo** (see §4).

---

## 1. What this is & where it lives

- Path: `/Users/ashwin/Desktop/marketlens` (NOT a git repo yet — consider `git init`).
- Stack: Python 3.11+ (dev machine has 3.13), FastAPI, SQLite (WAL), vanilla-JS SPA in
  `/static` (no build step). Data dir is `./data` (gitignored), set by `MARKETLENS_DATA_DIR`.
- Solo mode (default): `127.0.0.1`, no auth. Team mode: `MODE=team`, login required.

## 2. Run it / test it

```bash
cd /Users/ashwin/Desktop/marketlens
source .venv/bin/activate              # venv already exists (Python 3.13)
python app.py                          # http://localhost:8000
python -m pytest -q                    # 102 tests, all should pass, ~1s (network mocked)
python seed_demo.py                    # (re)create the Acme Cola / Singapore demo project
```

Docker path also works: `docker compose up`. Non-Docker setup scripts: `setup.sh`/`setup.bat`.

## 3. Module map

| File | Responsibility |
|---|---|
| `app.py` | FastAPI routes + static SPA mount + startup (migrations, admin bootstrap, scheduler) |
| `settings.py` | Env-derived config. **Note:** empty `HOST=`/`PORT=` fall back to defaults |
| `config.py` | Intake **wizard** + source-plan generation + Google News **and Bing News** URL builders + `feed_health_check` + country table (incl. **demonyms**) |
| `storage.py` | Persistence, **dedup** (content_hash, project-scoped), **near-duplicate/syndication clustering** (`cluster_id`), lineage, audit log, users |
| `migrations.py` | Idempotent `PRAGMA user_version` migrations (append-only) |
| `http_client.py` | One retrying session + per-domain rate limiting |
| `jobs.py` | **Single-writer job queue** + `run_collection` (the runner wrapping start_run/save_items/finish_run) |
| `scrapers/` | One module per channel + `base.py` (ScrapeResult) + `relevance.py` (strict content validation) |
| `analysis.py` | Claude batch tagging (12/batch, idempotent) + `call_claude()` helper |
| `analytics.py` | Aggregations, **every result carries `n`** + low-confidence flag (<100) |
| `market_intel.py` | Cited layer (enforced citations) + Manual Intelligence (Tier-2 deep links) |
| `source_discovery.py` | **AI source suggestions** + validation + RSS autodiscovery |
| `export.py` | Styled Excel (all tabs + "All Items" combined tab + version stamp) |
| `report.py` | 5-pillar Markdown draft + `.md`/`.docx` file outputs |
| `auth.py` / `archive.py` / `scheduler.py` | Team auth / project `.mlz` export-import / recurring runs |
| `static/{index.html,app.js,style.css}` | SPA: workflow stepper, Items browser, all tabs |
| `tests/` | pytest (network mocked) |

## 4. Reset local state to shipped/pristine

```bash
pkill -f "app.py"; rm -rf data && python seed_demo.py
```

---

## 5. What's DONE (feature-complete & tested)

- Data layer: dedup never inflates, lineage, project isolation, migrations, purge.
- Wizard: source plan per market/category; Google News `hl/gl/ceid`; GDELT code; subreddit
  suggestions; segment switches; `market_terms`/`cctld`; feed-health check.
- All 10 Tier-1 scrapers + strict relevance validation.
- Single-writer job queue + runner + job-status endpoint.
- Analysis (Claude, idempotent, retryable) + analytics with n-sizes + dashboard.
- Market Intelligence (cited, enforced citations) + Manual Intelligence + Tier-3 gaps.
- Export: Excel (Summary/Methodology/Confidence/Representativeness/Analysis Summary/Cited/
  Run Log/**All Items**/per-channel), version-stamped; Report draft (Markdown + Word/.docx).
- **News market filter** (drops off-market items via outlet ccTLD/market terms) — big win.
- **AI source discovery** (Source plan → "✨ Suggest sources") with validation + RSS autodiscovery.
- Distribution: team auth, archive import/export, scheduler, Docker, setup scripts, README.
- SPA: 4-step workflow stepper, per-tab help, key-detection chips, **Items browser** (filter
  by channel/brand_focus/sentiment/search), Collect market toggle.
- Demo: `seed_demo.py` (Acme Cola / Singapore — fictional, no fabricated data).
- **Four structural gaps closed** (a dedicated session pass — see §11 for design rationale
  on each; all live-verified against real Malaysia/Maggi data, not just unit tests):
  1. **Near-duplicate/syndicated-story clustering** (`cluster_id`) — wire stories reprinted
     across outlets no longer inflate sentiment n-size; `total_stories` vs `total_items` in
     every dashboard/export, nothing ever deleted.
  2. **Market-filter demonym false-negatives** — country reference table now has real
     demonyms (France→French, not just substring luck like Malaysia→Malaysian); wizard
     auto-populates `market_terms` with both.
  3. **Semantic relevance backstop** — Google/Bing News items with NO literal keyword match
     anywhere on the page (not just boilerplate) are stored, not dropped, and Claude's
     existing `brand_focus` tag makes the final call during Analyze (excluded from headline
     stats until then via `analytics._analyzed_rows(exclude_unrelated=True)`). Confirmed
     footer-only/junk matches are still always hard-dropped — this distinction
     (`relevance.term_appears_anywhere`) is the crux of the fix; get it wrong and you
     regress the tool's core "footer mention ≠ relevant" guarantee.
  4. **Bing News as a second, independent index** — no API key, its redirect resolves via a
     normal HTTP chain (unlike Google's encrypted token) so it can carry real first-
     paragraph text; wizard generates it alongside Google News automatically; no date-range
     support so it runs once per collection, not chunked.

## 6. KNOWN LIMITATIONS (honest constraints — do NOT try to "fix" by faking)

- **Google News article bodies are still unresolvable** (encrypted URL token; base64-decode
  + redirect-follow both fail, tested live) — `text` stays title-level, `extra.body_resolved=
  false` flags it. **Mitigated, not eliminated**, by direct publisher RSS feeds AND the new
  Bing News channel (§5.4) — both give real first-paragraph text. Do not build a GN
  de-obfuscator.
- **Market filter is strict by design** — drops items with no in-market signal; can still
  over-drop (neutral-titled local articles from an unknown-ccTLD outlet using neither the
  country name nor its demonym). Toggleable (`market_only`) and editable (`market_terms`,
  now demonym-aware — §5.2). Tune, don't remove the honesty.
- **Reddit/GDELT** get 403/429 from some IPs (incl. this dev sandbox) — handled as honest
  partial failures. Works better from a residential IP.
- **GDELT's own server-side relevance matching is loose/unreliable** — it can return country
  news totally unrelated to the query (a real live bug caught this session: 175 of 202
  "results" were noise). `scrapers/gdelt.py` now re-validates each title against relevance
  terms before storing (`irrelevant_dropped` diagnostic) — but expect GDELT's real yield for
  a narrow brand+country query to be small; it's a broad event index, not a brand-review
  source.
- **Quick-commerce & most social** are app-only / anti-automation → **documented Tier-3
  gaps**, never scrapers. Keep it that way — this is NOT one of the "structural gaps" to fix.
- E-commerce needs `python -m playwright install chromium` (baked into the Docker image).
- Report export is `.md` + `.docx` only (no PDF yet).

## 7. PENDING / SUGGESTED NEXT WORK (pick up here)

Offered to the user but not yet built (in rough priority order):
1. **"Add all validated e-commerce + RSS" one-click button** in the Suggest-sources panel.
2. **Suggested-RSS-feeds baked into the wizard** per country (still user-confirmed via health check).
3. **Edit-study-settings form** (change market/brand/competitors and regenerate the source
   plan in place — today the market is only set at wizard time).
4. **Delete-study button** in the UI (backend `DELETE /api/projects/{id}?confirm=DELETE` exists).
5. **"target brand only" export filter** (drop `brand_focus=unrelated` rows) — partially
   superseded now: headline aggregates already exclude `unrelated` by default (§5.3); this
   would just add an explicit toggle for the raw data tabs too.
6. **Auto-suggest city/region market terms** to further reduce market-filter over-drop
   (demonyms are now automatic — §5.2 — but city/region-level terms still require the user
   to add them manually in Source plan, or come via ✨ Suggest sources).
7. **PDF report export**; **per-tab description headers** in the Excel (self-documenting).
8. Real end-to-end validation with `YOUTUBE_API_KEY` / `GOOGLE_PLACES_API_KEY` set.
9. Surface `relevance_recovery_stats()` and the Bing/Google split in the Analysis tab UI
   (currently API + Excel Confidence tab only, no dedicated frontend chart yet).

## 8. Gotchas discovered this session (save yourself the debugging)

- **`.env` is a hidden dotfile.** Created from `.env.example`. `ANTHROPIC_API_KEY` is required
  for Analysis, image vision, and Suggest-sources. ⚠️ The user pasted a real key into chat
  earlier — **it must be rotated/revoked**; do not reuse it.
- **The venv was originally bootstrapped with a subset of deps.** If you hit
  `ModuleNotFoundError` (e.g. `anthropic`, `pytrends`, `Pillow`, `python-docx`, `playwright`),
  run `pip install -r requirements.txt`.
- **Port 8000 in use:** `lsof -ti:8000 | xargs kill -9`, or set `PORT=`.
- **Excel data lives on the last tabs** ("All Items", per-channel) — scroll the sheet-tab
  strip right; macOS Quick Look only shows one sheet (open in Excel/Numbers).
- **Workflow order matters:** Source plan only defines *where* to look; you must run
  **Collect → Analyze** before Export/report have content. The UI stepper now enforces this
  visually.
- The in-app browser-preview tool had intermittent tab-click issues — that's a preview-pane
  artifact, **not** an app bug (tabs work fine in a real browser).

## 9. Working conventions

- Match existing code style (dense but commented; lazy imports for heavy optional deps).
- Add/extend a pytest for every behavior change; keep the suite green and network-free.
- Keep `version.py` in sync if you cut a release; migrations are append-only.
- After local runs: reset data (§4) so the shipped state stays the clean demo.

---

## 10. Data model (SQLite)

- `projects(id, name, config_json, created/updated)` — config is the wizard output (JSON).
- `runs(id, project_id, channel, params_json, status, started/finished, rows_returned/new/
  duplicate, errors_json, triggered_by)` — one per collection; the lineage anchor.
- `items(id, project_id, run_id, source, content_hash, title, text, link, published,
  extra_json, created_at)` — **UNIQUE(project_id, content_hash)**.
- `analysis(item_id UNIQUE, project_id, model, sentiment, sentiment_score, language,
  summary_en, rating_signal, purchase_driver, usage_occasion, trend_category, brand_focus,
  promo_mentioned, emotion, raw_json)`.
- `market_intel(entry_type='cited'|'manual_ad', category, metric, value, source_name,
  source_url, publication_date, accessed_date, confidence, notes, extra_json, entered_by)`.
- `schedules`, `users`, `audit_log`.
- `items.cluster_id` (migration 002) — nullable INTEGER, near-duplicate/syndication group.
  **Legacy rows (pre-migration) have `cluster_id=NULL`** — always read via
  `COALESCE(cluster_id, id)`, never bare `cluster_id`, or you'll silently undercount (SQL
  `COUNT(DISTINCT x)` ignores NULLs entirely). `storage.count_unique_stories`/`cluster_sizes`
  already do this correctly; if you add a new query touching `cluster_id`, do too.

## 11. Design decisions & rationale (the non-obvious "why")

- **content_hash excludes project_id** = `sha256(source|link|title|text[:200])`. So the same
  content in two projects yields the same hash; **project isolation is the composite
  UNIQUE(project_id, content_hash)**, not the hash. This is deliberate and tested — don't
  "simplify" it by hashing project_id in.
- **Single-writer job queue** (`jobs.py`): SQLite + one worker thread = no write contention,
  and User B sees User A's running job. Scrapers are *pure collectors* (return items+errors,
  never touch the DB); the runner is the only place that writes → identical lineage/dedup for
  every channel and trigger.
- **News market filter uses the OUTLET's ccTLD**, obtained from the feed's `<source url>`
  (e.g. `nst.com.my`), because the *article* URL is an obfuscated Google News redirect we
  can't resolve. This is the key trick that removed Indian coverage from a Malaysia study.
- **Relevance validation strips boilerplate BEFORE matching** so a brand name that only
  appears in a "related articles" rail correctly fails. Headline match short-circuits to
  relevant; otherwise the real body is fetched and checked.
- **Every analytics aggregate carries `n`**; <100 → "low-confidence" flag, surfaced in the
  Confidence tab and report. "Decision-grade" means numbers never hide their sample size.
- **AI source discovery suggests, the tool validates.** LLMs know outlets but hallucinate RSS
  paths — so guessed feeds are health-checked and, if dead, the real feed is auto-discovered
  from the homepage `<link rel="alternate">`. Nothing dead/fake is auto-added.
- **Clustering never deletes or merges rows** — `cluster_id` groups near-duplicate titles
  (similarity + tight date window) purely for *counting*; `total_items` (raw) and
  `total_stories` (syndication-adjusted) are both always reported, never one silently
  swapped for the other. A recurring PR headline a year apart ("Cooking Competition
  Returns") must NOT cluster — the date window is what prevents that false merge; don't
  widen it carelessly.
- **Demonyms are an explicit table field, not derived.** `"Malaysia" ⊂ "Malaysian"` worked by
  substring luck; `"France" ⊄ "French"` doesn't. Never assume a demonym can be computed from
  the country name — always look it up.
- **The semantic-relevance backstop only applies to QUERY-SCOPED feeds** (Google/Bing News,
  `is_google_news=True` — the flag now means "keyword-scoped feed," not literally "is this
  Google"), never to raw RSS (an unscoped full firehose with no volume bound at all if
  relaxed). And it only fires when the term is absent from the ENTIRE page — if it's present
  ONLY in stripped boilerplate (`relevance.term_appears_anywhere` says yes but
  `contains_any_term` on the stripped body says no), that's CONFIRMED junk and still hard-
  drops. Conflating these two "relevant=False" cases was a real regression caught by the
  pre-existing footer-junk test this session — if you touch this logic, run
  `tests/test_relevance.py` and `tests/test_news.py` together.
- **Bing News's redirect is a normal HTTP chain** (`apiclick.aspx?...&url=<real-dest>`),
  unlike Google News's encrypted opaque token — `resolve_and_fetch()` needed ZERO special-
  casing for it, the existing non-Google branch (plain `fetch()` + follow redirects) already
  handles it. This is why Bing can carry real first-paragraph text where Google News cannot.
  No date-range operator though, so it's collected once per run, not month-chunked.

## 12. API keys — which channel needs what

| Env var | Powers | Notes / where to get |
|---|---|---|
| `ANTHROPIC_API_KEY` | Analysis, image vision, **Suggest-sources** | console.anthropic.com. Analysis = 12 items/Claude call; model configurable (`ANALYSIS_MODEL`, default `claude-haiku-4-5`). |
| `YOUTUBE_API_KEY` | YouTube channel | Google Cloud → YouTube Data API v3. Quota-limited. |
| `GOOGLE_PLACES_API_KEY` | Google Business reviews | Google Cloud → Places API. Returns a capped review sample. |
| `TWITTER_API_KEY` | Twitter/X manual intel (optional) | third-party X API. |

No-key channels that work out of the box: **News, GDELT, Reddit** (also Forums/Quora once
you add URLs). E-commerce needs the Playwright browser.

## 13. User context (who you're building for — from the prior session)

- Non-deeply-technical user running this on a Mac. Main study of interest: **Maggi in
  Malaysia** (instant noodles, FMCG). The demo ships as Acme Cola / Singapore.
- Real friction points they hit (design the UX around these):
  - Didn't realize **Collect + Analyze must run before Export/report have content** — the
    workflow stepper + per-tab help were added for this. Keep reinforcing the pipeline.
  - Struggled to **find collected items in the Excel** (they're on the last tabs) — the
    in-app **Items browser** and the combined **"All Items"** tab were added for this.
  - Wanted **geography-correct results** (Malaysia not India) → market filter.
  - Wanted the tool to **auto-populate sources** → AI source discovery.
  - Asked "is this enterprise grade?" meaning **data quality/completeness**, not
    infra/compliance — led to a full pass identifying and fixing 4 structural gaps
    (clustering, demonyms, semantic relevance, second news index — see §5.4/§11). The user
    explicitly chose the bigger-but-correct architecture option for the relevance fix
    (folded into existing Analyze, no extra API calls) over a cheaper opt-in-cost option —
    they lean toward "do it right" over "do it cheap" when asked directly.
  - Their Malaysia study's item count went 7 → 39 → 40 (cleaned) → 187 (enriched, but noisy
    — later found to include 175 GDELT junk items) → 27 (GDELT-noise removed) over the
    course of debugging. **If total_items looks suspiciously large or small, check
    `relevance_recovery_stats()` and `cluster_sizes()` before assuming the number is real.**
- Implication: favor **guided, self-explanatory UX and honest status** over raw features.
  When something can't be done reliably (GN bodies, app-only platforms), say so in the UI
  rather than silently degrading. When the user flags a data-quality concern, verify it
  live against real sources before fixing — three of the four structural-gap fixes this
  session were caught/confirmed by actually running collection against live Malaysia data,
  not by reasoning from the code alone.

