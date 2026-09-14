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
- Stack: Python 3.11+ (dev machine has 3.13), FastAPI, SQLite (WAL), React + Vite SPA
  (source `/frontend`, built into `/static`, committed — see CLAUDE.md's Frontend section;
  this replaced an earlier vanilla-JS/no-build-step frontend). Data dir is `./data`
  (gitignored), set by `MARKETLENS_DATA_DIR`.
- Solo mode (default): `127.0.0.1`, no auth. Team mode: `MODE=team`, login required.

## 2. Run it / test it

```bash
cd /Users/ashwin/Desktop/marketlens
source .venv/bin/activate              # venv already exists (Python 3.13)
python app.py                          # http://localhost:8000
python -m pytest -q                    # 162 tests, all should pass, ~1.4s (network mocked)
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
| `term_expansion.py` | **AI term expansion** — variants/brands/translations for a narrow term |
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
- **AI term expansion** (`term_expansion.py`; Source plan → "✨ Expand a term") — closes a
  real precision AND volume gap: a narrow everyday term (e.g. "coffee") hides product
  variants (instant coffee, cold coffee, latte, cappuccino, americano...), real brand/shop
  names people search for instead (Starbucks, Costa Coffee, ...), and equivalents of all
  of that in the study's OTHER configured languages — so a naive single-keyword study
  only ever sees the one literal word typed in. Same suggestion+validation posture as AI
  source discovery: Claude proposes, nothing is written until the user reviews and
  confirms via `POST .../apply-terms`. Each confirmed variant/brand/translation becomes
  its OWN keyword structure (own News feed, own ~100-result ceiling — the mechanic
  `config.regenerate_news_feeds` already relies on), and brands are also added to
  `competitors` so the existing `brand_focus` analysis tagging picks them up for free.
  Live-verified end-to-end against a real India/coffee study (project #14): the LLM
  returned 12 genuine variants (instant/cold/filter coffee, cappuccino, espresso, iced/
  black coffee, ...), 12 real India-specific brands (Nescafé, Bru, CCD, Blue Tokai,
  Starbucks, Café Coffee Day, Lavazza, Indian Coffee House, Araku, Twenty Third Street
  Coffee, ...) — not generic global names — and correct native-script translations across
  all 8 non-English configured languages (e.g. Hindi: कॉफी / इंस्टेंट कॉफी / कोल्ड कॉफी).
  Applying the selections took the project from 15+15 to **87 Google News + 87 Bing News
  feeds**. A non-Latin-script structure-key collision bug was caught and fixed before
  shipping: two different Hindi variants both slugged to the generic key "term" and would
  have silently overwritten each other — `term_expansion._slug()` now falls back to the
  item's list index when the text has no [a-z0-9] to slug from, guaranteeing uniqueness.
- Distribution: team auth, archive import/export, scheduler, Docker, setup scripts, README.
- SPA: 4-step workflow stepper, per-tab help, key-detection chips, **Items browser** (filter
  by channel/brand_focus/sentiment/search), Collect market toggle.
- **Target-languages picker**: intake wizard's language field is a native `<select multiple>`
  (single- AND multi-select in one control — click for one, Cmd/Ctrl/Shift-click for
  several) backed by `config.LANGUAGE_TABLE`/`list_languages()` (54 ISO 639-1 languages,
  a generic reference table) via `GET /api/reference/languages`. A free-text "other codes"
  field alongside it covers anything not in the list, so no language is ever unreachable.
  Live-verified in the browser: selected Bulgarian + Croatian via click + Cmd-click,
  submitted, and the created project's config carried exactly `["bg","hr"]`.
- **Country/region picker**: same `<select multiple>` treatment, backed by
  `config.COUNTRY_TABLE`/`list_countries()` (deduped by canonical name — the table has
  alias keys like `"usa"`/`"united states"` that must not show as two dropdown rows) via
  `GET /api/reference/countries`, plus a free-text "other" field for anything not listed.
  Unlike languages, a study targets exactly ONE market — every downstream consumer
  (`config.py`'s GDELT/Google News/ccTLD/market_terms generation) expects `market.country`
  as a single string, not a list — so more than one selection is a hard reject, not a
  silent pick-one: enforced in `app.py`'s `/api/projects/wizard` (a single-item list is
  normalized to a plain string; 2+ items → 400) AND in the form's JS for fast feedback.
  Live-verified in the browser end-to-end, including the rejection path: selecting
  Australia + Brazil and submitting produced the toast "A study targets one
  country/region — you selected 2 (Australia, Brazil). Pick just one." with nothing
  sent to the server; correcting to a single "Canada" click then submitting produced
  `market.country: "Canada"` (normalized from the one-item list) with the full pipeline
  (ISO/GDELT/ccTLD/market_terms/News feeds) built correctly from it.
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
- **Five more channels fixed after live testing exposed real bugs** (Reddit/Forums/Quora/
  E-commerce fully live-verified; Trends fixed + unit-tested, live confirmation
  inconclusive — see §6):
  1. **Reddit: migrated `.json` → `.rss`.** Reddit's old unauthenticated JSON endpoints are
     now hard-blocked (403 from Reddit's own edge, confirmed live, not a UA/IP issue). The
     legacy `.rss` (Atom) feeds still work. Also fixed a real parsing bug: feedparser needs
     raw response **bytes**, not `.text` (a pre-decoded string), or it silently returns 0
     entries on some responses. Reddit's RSS rate limit is tight (verified live: sub-5s
     spacing reliably 429s) — added a Reddit-specific wait-and-retry (`RETRY_429_WAIT`/
     `RETRY_429_ATTEMPTS` in `scrapers/reddit.py`), plus 429 added to `http_client.py`'s
     global retry-on-status list. Live-verified: 79 items (75 posts, 4 real comments).
  2. **Forums: selector picking is now scored, not first-match-wins.** Verified live against
     forum.lowyat.net that the old logic latched onto a broad `[class*=post]` wildcard
     matching mostly chrome (timestamps, "Show posts by this member only") before ever
     trying anything content-specific. Now tries known-good platform classes first
     (`.postcolor` for IPB/IP.Board, etc.), scores every candidate by the AVERAGE length of
     substantial (≥40 char) matches — favors real prose over numerous-but-short chrome —
     and only falls back to wildcards if nothing specific matched. Live-verified: went from
     82 chrome fragments to 8 real posts on the same real thread.
  3. **Google Trends: pytrends' own retry is broken.** Its `retries=`/`backoff_factor=`
     constructor args build a `urllib3.Retry(method_whitelist=...)` — a kwarg removed from
     current urllib3 — so passing them crashes with `TypeError` (confirmed live; this is why
     pytrends silently defaults to `retries=0`, and it's the latest available version, so not
     upgradable away). `scrapers/trends.py` now wraps every pytrends call with its own
     retry-with-backoff instead. Unit-tested thoroughly; **live end-to-end success is
     unconfirmed** — see §6.
  4. **Quora: wasn't actually broken — improved diagnostics.** Live-tested and confirmed the
     channel already behaved correctly (0 items, honest per-URL errors, no fabrication) — the
     real fix was making the error message specific instead of generic. Quora sits behind a
     Cloudflare managed bot-challenge ("Just a moment..." JS-challenge, HTTP 403) on every
     request, confirmed universal across URLs/UAs — harder than Reddit's block since it needs
     real JavaScript execution, not fixable with `requests`. `scrapers/quora.py` now detects
     this specifically (`_cloudflare_challenge`, `_block_reason`) instead of a vague "likely
     blocked". First test coverage this channel has ever had (0 → 7 tests).
  5. **E-commerce: detect bot-blocks instead of silently storing them as data.** Real bug
     found live: Shopee returns a soft bot-block ("Page Unavailable... please log in and try
     again") for every headless request — the scraper was storing this as a legitimate item
     (real title, 0 chars of body) with **zero errors logged**, a genuine "never fabricate"
     violation. Added two-layer detection (`_looks_blocked` in `scrapers/ecommerce.py`): known
     block-page markers + a minimum-content-length fallback (verified live: Shopee's block
     response varies, and the length heuristic caught a variant the marker list didn't).
     Live-verified against two real Malaysian marketplaces: Shopee blocked on every attempt
     (now correctly detected, confirmed with two different block variants); Lazada renders
     real content (verified with genuine Maggi products/prices) and still collects correctly
     after this fix (no false positive). Lazada's reviews did not trigger the XHR-based
     review-interception heuristic even after scrolling — deliberately NOT chased further
     (fragile, site-specific, could break on the next redesign, against this tool's own
     philosophy); page-level text (titles/prices/descriptions) is still real, working signal.
- **Category-only studies (no single target brand) are now fully supported.** Until this
  change, `brand` was a hard `required` field in the intake form — but the backend
  (`config.py`'s relevance-term derivation, keyword scaffolding, `analysis.py`'s
  `brand_focus` vocabulary which already had a `"category-generic"` bucket) was already
  brand-optional; only the intake form and one prompt-builder assumed brand always exists.
  Fixed: intake now requires brand OR category OR both (enforced server-side in `app.py`'s
  `/api/projects/wizard`, not just the form JS); `source_discovery.py`'s AI-suggest prompt
  no longer sends `the product ""` / an empty e-commerce query term when brand is absent —
  it describes the study as category-wide and uses the category as the query term instead.
  Live-verified end-to-end against the running server: a "Malaysia / instant noodles / no
  brand / competitor=Indomie" study created cleanly (HTTP 200), named itself "instant
  noodles" (not "Untitled study"), derived `relevance_terms: ["Indomie","instant","noodles"]`,
  generated real working Google+Bing News RSS URLs from the category term, and correctly
  left `google_business.query` empty (no named entity to search for a business listing).
- **DESIGN_01 category-discovery rollout complete (increments 1-9)**, including the final
  generalization increment (#9): tested skincare/Brazil and electric scooters/Vietnam
  end-to-end through the real, live pipeline (not mocked), finding and fixing 4 real bugs
  the narrower coffee/India pilot never exercised — all in `source_type_mapping.py`/
  `sitemap_discovery.py`, all live-verified before/after, all with regression tests. See
  git log ("Increment 9: fix 4 real bugs...") for full detail; throwaway verification
  projects/ledger rows cleaned up afterward.
- **Edit-study-settings form** (`frontend/src/wizards/EditSettingsModal.jsx` +
  `config.update_settings()` + `POST /api/projects/{id}/update-settings`) — change
  market/brand/competitors after a study is already created, not just at wizard time.
  Recomputes only the fields that are pure functions of market/product/competitors
  (feeds, gdelt/youtube/google_business templates, segments); every hand-filled
  source_plan URL list and every existing language's keyword structures are preserved
  untouched; `market_terms`/`subreddits`/`relevance_terms` are merged (union), never
  replaced, so a real AI-assist addition on top of the mechanical default is never
  silently erased. Known, accepted trade-off: switching a field back and forth leaves
  the intermediate value's derived terms/subreddits behind too (harmless noise, easy to
  remove by hand) — see `config.update_settings()`'s docstring. Live-verified end-to-end
  in the browser (changed the demo project's country live, confirmed feeds/gdelt
  recomputed correctly, then reverted and re-seeded to undo the resulting market_terms
  drift this trade-off causes).
- **Delete-study button** (`frontend/src/components/ConfirmDeleteModal.jsx`) — the
  existing `DELETE /api/projects/{id}?confirm=DELETE` backend now has a UI: type the
  exact study name to enable the confirm button (a plain Yes/No felt too weak for a
  genuinely irreversible purge of every item/run/audit row). Live-verified: created a
  throwaway project, deleted it through the modal, confirmed via direct API call it was
  gone and the UI correctly fell back to the remaining project.
- **One-click "add all validated" button** (Source plan → ✨ Suggested sources) — bulk-
  accepts every `valid !== false` News RSS + e-commerce candidate straight into the
  source plan, skipping the per-row checkbox review for when the suggestion list is long.
- **Real-time in-run progress for News/GDELT jobs** (Collect stage) — job status was a
  flat queued/running/done/error; a full-year Extensive run across many feeds could sit
  on "running" for minutes. `jobs.py`'s job dict now carries an optional `progress`
  ({current, total, label}); `scrapers/news.py`/`scrapers/gdelt.py`'s `collect()` gained
  an optional, purely-additive `progress_cb` called after each feed x date-chunk, wired
  through `jobs.run_collection()` only for channels whose signature accepts it
  (introspected, not assumed — every other channel's call site is untouched). Surfaces
  automatically (no API change) in the Collect tab's job table (fill-bar + step label)
  and the topbar chip (`{channel} {pct}%`). Live-verified against a real full-year
  Extensive news job on the demo project: watched 1/52 → 52/52 climb via direct polling
  and in the browser, confirmed a real 86-item completion summary.
- **Suggested-RSS-feeds baked into the wizard** (HANDOFF §7 item 1) — the same
  ✨ Suggest sources → validate → confirm flow (extracted into
  `frontend/src/components/SuggestSourcesPanel.jsx`, shared with Source plan) now runs
  as an optional second step right after `NewStudyWizard.jsx` creates a study, instead
  of requiring the user to remember Source plan afterward. Live-verified against a real
  Vietnam study: real Claude-suggested RSS candidates, each independently feed-health-
  checked (VietnamNet correctly flagged `HTTP 404 (autodiscovery failed)`, Thanh Niên
  came back valid), added via "Add all validated" and confirmed persisted via a direct
  API call. Finding this live also surfaced a real, independent, pre-existing bug (next
  bullet) that would have silently defeated this whole feature.
- **Real bug found + fixed: creating a study while another was already open didn't
  switch focus to the new one** — see §8's gotchas entry for the root cause
  (`AppState.loadProjects()`'s re-selection logic) and the fix (`selectProject()` called
  explicitly in both `NewStudyWizard.jsx` and `DiscoveryWizard/index.jsx`).
- **"Target brand only" export filter** (HANDOFF §7) — `export.build_workbook(...,
  exclude_unrelated=True)` drops `brand_focus == "unrelated"` rows from the raw data
  tabs (All Items + per-channel), matching the same exclusion `analytics.py`'s headline
  stats already apply by default (`_analyzed_rows(exclude_unrelated=True)`) — until now
  that consistency only held for the aggregate numbers, not the raw rows a client might
  pivot on directly. Off by default (nothing is ever silently hidden unless opted in);
  the Summary tab documents which mode was used, in both directions. Wired through
  `POST /api/projects/{id}/export`'s `exclude_unrelated` body field and a checkbox in
  Export.jsx.
- **Auto-suggest city/region market terms** (HANDOFF §7, new `geo_term_discovery.py`) —
  the same demonym-style market-filter gap one geographic level down: an article naming
  only a city/region, never the country, is genuinely in-market but undetected unless
  that place is already a market term. Same suggestion+validation posture as
  `outlet_discovery.py`: Claude proposes REAL, category-relevant cities/regions in the
  study's market (major consumption/manufacturing hubs for THAT category, not just the
  biggest cities generically), candidates already in `market_terms` are dropped up
  front, and nothing is written until confirmed. Reuses `outlet_discovery.apply_outlets()`
  for the actual write (same target field, same dedup semantics) rather than duplicating
  an apply path — `POST /api/projects/{id}/apply-outlets` now takes an optional `kind`
  field so the audit log reads accurately either way ("local outlet(s)" vs "city/region
  market term(s)"). New `POST /api/projects/{id}/suggest-market-terms` endpoint; a
  "✨ Suggest city/region market terms (AI)" card in Source plan, right after outlet
  discovery. Live-verified against the real demo project (Singapore/carbonated soft
  drinks): real, specific, category-relevant suggestions came back (Orchard Road, Jurong,
  Changi, Marina Bay, ... — each with a genuine category-specific "why," not generic
  biggest-cities filler), applied 2 of them, confirmed persisted via a direct API call,
  and confirmed the audit log correctly read "Added 2 city/region market term(s)."
- **PDF report export + per-tab Excel description headers** (HANDOFF §7) —
  `report.save_pdf()` renders the Markdown report via a small Markdown->HTML subset
  (headings/bullets/bold/blockquote/hr — the exact fixed set `draft_report()` actually
  emits, confirmed by inspection, not a general Markdown parser) + fpdf2's built-in
  `write_html()`. **Real bug found live on the very first export attempt**: fpdf2's
  default core "Helvetica" font only supports latin-1/cp1252 and crashed
  (`FPDFUnicodeEncodingException`) on the report's OWN title line, which always
  contains an em dash. Fixed by bundling DejaVu Sans (`fonts/`, Bitstream Vera
  license — free to embed, see `fonts/DEJAVU_LICENSE.txt`) instead of a core font.
  Accepted, honest scope limit: DejaVu Sans doesn't cover Devanagari/Tamil/Telugu/CJK
  glyphs — not a real gap in practice, since `draft_report()` only ever renders
  English text (`summary_en`) plus Latin-Extended names; native-script `text` fields
  (`analytics.top_verbatims_per_theme()`) are never rendered raw. New `fmt=pdf` on
  the existing `GET /api/projects/{id}/report/download` endpoint; a "Download PDF"
  button in Export.jsx. Separately, `export._channel_data_tab()` now writes an
  italic, wrapped description row above the column headers on every raw data tab —
  "All Items" explains `story_group_size`; each per-channel tab reuses that
  channel's real `CHANNEL_INFO` method/limitation text (the SAME copy the Collect
  tab UI shows), so a tab opened on its own (detached from Methodology) still
  documents itself, and can never silently drift out of sync with the UI's own
  description. Live-verified: downloaded a real PDF from the running server
  (correct em dash/⚠ rendering, real section headings), and confirmed both
  description rows on a real built workbook.

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
- **Reddit's old `.json` API is dead** (Reddit blocks it outright, confirmed live) — fixed by
  migrating to `.rss` (§5's second list, item 1). Its rate limit is tight; still expect
  occasional 429s under heavy use even with the retry wrapper — handled as honest partial
  failures, never fatal.
- **GDELT** still gets 403/429 from some IPs (incl. this dev sandbox) — handled as honest
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
- **Google Trends (pytrends) rate-limits aggressively and its own retry is broken** (fixed
  with our own retry wrapper — §5's second list, item 3) — but this session could NOT get a
  live 200; every attempt across two separate testing sessions came back 429. **Confirmed
  IP-level, not app-level**: a plain `curl` against `trends.google.com/trends/api/explore`
  (no pytrends, no cookies) returns 429 directly, while `trends.google.com/trends/`
  (homepage) returns 200 — so this specific sandbox IP is throttled by Google's Trends API
  backend specifically, unrelated to our code or pytrends. **If you pick this up, try it
  from a different IP or after a long real-world cooldown (e.g. the next day)** — the retry
  mechanism itself is solid, unit-tested, and re-verified live (correct 2-retry/20s-backoff
  cadence, no crash, honest error, no fabricated data). Do not re-diagnose this as a code
  bug; it isn't one.
- **Reddit/Forums/Trends rate limits are all tighter than a typical read API** — if you're
  live-testing any of them, expect to need real multi-second-to-tens-of-seconds waits
  between requests, and don't hammer them back-to-back while diagnosing (this sandbox's
  own aggressive diagnostic testing is likely why Trends ended up unconfirmable above).
- **Quora is confirmed genuinely, permanently blocked** — do not spend time trying to fix
  this further short of adding a full headless-browser-with-challenge-solving path (out of
  scope; would also mean defeating an anti-bot system, which this tool does not do).
- **Shopee is confirmed genuinely, permanently blocked** the same way — a soft bot-wall on
  every headless request.
- **Lazada is now confirmed genuinely, permanently blocked at the product-page level —
  question closed, not open.** A later session got a fresh, uncontaminated IP/session
  (confirmed via the catalog page rendering clean real content again — 3,422 real "maggi"
  results, no CAPTCHA) and used it to isolate the original question precisely: does
  product-detail/review data load through a mechanism this tool could ever capture?
  Answer: no. Lazada's product pages fetch their data client-side from Alibaba's shared
  "mtop" API gateway (`mtop.global.detail.web.getDetailInfo`) — Lazada runs on Alibaba's
  infrastructure — and that gateway is gated by Alibaba's anti-crawler system. Proof: the
  *very first* request to that endpoint, on a never-before-touched product ID, with zero
  scrolling or interaction, came back `{"ret":["FAIL_SYS_USER_VALIDATE","RGV587_ERROR..."],
  "data":{...,"action":"captcharecaptcha"}}` — an immediate challenge, reproduced on a
  second fresh product ID too. This is a structural, per-request API-level block, not a
  rate-limit-after-abuse effect and not a "find the right UI sequence" problem — there is
  no tab-click fix for this. `scrapers/ecommerce.py`'s `_looks_blocked` already catches
  the resulting page correctly (CAPTCHA marker in raw HTML → error, nothing stored).
  **Same permanence tier as Quora/Shopee now — do not re-open this.** Search/catalog
  pages remain genuinely scrapable (real server-rendered HTML); only product-detail (and
  therefore reviews) is blocked.
- **Other Malaysian grocery platforms considered (Jaya Grocer, Lotus's/Tesco MY) and
  ruled out — architectural mismatch, not a bot-block.** Checked as candidate additional
  e-commerce sources for the same Maggi/Malaysia study. Neither is actually a good fit
  for this channel: their product pages are transactional grocery-delivery UX (buy
  button, price) with no customer review/rating system at all, so there's nothing to
  extract even when reachable. Their search is also a client-side JS widget hidden
  behind a click-to-reveal icon, not a plain `?q=` URL, so the existing "search-URL
  template + keyword" mechanism doesn't apply without reverse-engineering a per-site
  interaction sequence — the same category of fragile, site-specific chase this tool
  already declines to do for Lazada's review tab. Not worth pursuing further; Shopee +
  Lazada (search/catalog only) remain the two real e-commerce sources for this market.

## 7. PENDING / SUGGESTED NEXT WORK (pick up here)

Offered to the user but not yet built (in rough priority order):
1. Real end-to-end validation with `YOUTUBE_API_KEY` / `GOOGLE_PLACES_API_KEY` set — **no
   keys are configured in this environment's `.env`** (checked live), so this cannot be
   done from here; needs the user to supply real keys in their own `.env` (never pasted
   into chat — see §0's security note) and run it themselves, or hand it to a session
   that has them.
2. Surface `relevance_recovery_stats()` and the Bing/Google split in the Analysis tab UI
   (currently API + Excel Confidence tab only, no dedicated frontend chart yet).
3. **Confirm Google Trends live** from a fresh IP or after a real cooldown (§6) — re-tested
   this sandbox again and confirmed the 429 is IP-level, not app-level: plain `curl` (no
   pytrends, no cookies) against `trends.google.com/trends/api/explore` returns 429 directly,
   while `trends.google.com/trends/` (homepage) returns 200 — so it's specifically this
   sandbox IP being throttled by Google's Trends API backend, not a code issue. The
   retry-wrapper fix itself re-verified correct (clean 2-retry/20s-backoff cadence, no crash,
   honest error surfaced, no fabricated data). Nothing left to fix in code — only a fresh
   IP or a long real-world cooldown can produce a live 200 here; not actionable from here.

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
- **Real bug, fixed live: creating a study while another was already open didn't switch
  focus to the new one.** `AppState.loadProjects()` only re-selects when the CURRENTLY
  selected project id no longer exists in the list — after creating a second study while
  #1 was active, #1 still exists, so it silently kept showing #1's market/config while the
  sidebar dropdown WAS updated to include the new one. Both `NewStudyWizard.jsx` and
  `DiscoveryWizard/index.jsx` now call `selectProject(newId)` explicitly right after
  creation, not just `loadProjects()`. No frontend test runner exists in this repo (Python
  pytest only — `frontend/package.json` has no Jest/Vitest); verify any frontend logic
  change live in the browser (create project #1, then #2, confirm the dropdown AND the
  page content both reflect #2), the same way this bug was actually found.

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

