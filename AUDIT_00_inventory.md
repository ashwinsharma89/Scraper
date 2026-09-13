# AUDIT_00 — Repository Inventory

Scope: `/Users/ashwin/Desktop/marketlens` ("MarketLens"). Purely descriptive — no analysis, no
recommendations. All facts below were obtained by direct inspection (`find`, `wc -l`, `git log`,
`pip freeze`, file reads) on the date this audit was run.

---

## 1. Full directory tree

```
marketlens/
├── .claude/settings.json          # Claude Code tool-permission allowlist for this repo
├── .dockerignore
├── .env                           # local secrets — gitignored, see §6
├── .env.example                   # template for .env
├── .gitignore
├── .pytest_cache/                 # pytest artifact, 36K
├── .venv/                         # Python 3.13.5 virtualenv, 349M — vendored, not inspected file-by-file
├── __pycache__/                   # compiled bytecode, 284K — artifact
├── CLAUDE.md                      # auto-loaded session context (not app code)
├── HANDOFF.md                     # engineering handoff doc (not app code)
├── README.md                      # product-facing docs
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── setup.sh / setup.bat           # non-Docker install scripts
├── version.py                     # single version constant
│
├── app.py                         # FastAPI app: all HTTP routes + static mount + startup
├── settings.py                    # env-var-derived config object
├── config.py                      # intake wizard + source-plan/keyword/feed-URL generation
├── storage.py                     # SQLite persistence layer (raw sqlite3, no ORM)
├── migrations.py                  # PRAGMA user_version schema migrations
├── jobs.py                        # single-writer in-process job queue + runner
├── http_client.py                 # shared requests.Session with urllib3 Retry
├── analysis.py                    # Claude batch-tagging of collected items
├── analytics.py                   # aggregation queries over analyzed items
├── source_discovery.py            # AI-suggested source URLs (news/ecommerce/forums/subreddits)
├── term_expansion.py              # AI keyword/term expansion (variants/brands/translations)
├── market_intel.py                # manually-entered, cited market-fact records
├── export.py                      # openpyxl Excel workbook builder
├── report.py                      # Markdown/.docx narrative report builder
├── archive.py                     # .mlz (zip) project export/import
├── auth.py                        # session-cookie auth for "team" mode
├── scheduler.py                   # in-process interval loop for recurring collection jobs
├── seed_demo.py                   # populates the "Acme Cola" demo project
│
├── scrapers/
│   ├── __init__.py                # CHANNEL_INFO registry + collect() dispatch
│   ├── base.py                    # ScrapeResult dataclass-like helper, relevance_terms()
│   ├── relevance.py               # HTML-boilerplate-stripping + term-match validation
│   ├── news.py                    # Google News / Bing News / direct RSS (largest scraper, 495 lines)
│   ├── gdelt.py                   # GDELT DOC 2.0 API client
│   ├── reddit.py                  # Reddit via public .rss endpoints (not the JSON API)
│   ├── forums.py                  # generic HTML forum-thread scraper (BeautifulSoup + heuristics)
│   ├── quora.py                   # Quora page fetch + Cloudflare-block detection
│   ├── ecommerce.py                # Playwright-driven marketplace scraper + bot-block detection
│   ├── youtube.py                 # YouTube Data API v3 client (needs YOUTUBE_API_KEY)
│   ├── google_business.py         # Google Places API client (needs GOOGLE_PLACES_API_KEY)
│   ├── trends.py                  # pytrends (Google Trends) wrapper with custom retry
│   └── image_analysis.py          # Claude vision analysis of images already collected
│
├── static/
│   ├── index.html                 # SPA shell + intake-wizard form markup
│   ├── app.js                     # entire SPA logic, 1102 lines, no build step, no framework
│   └── style.css
│
├── tests/                         # 26 files, 3020 lines total, pytest, all network mocked
│
├── data/                          # runtime data dir (MARKETLENS_DATA_DIR), 2.2M
│   ├── marketlens.db              # live SQLite database
│   ├── archives/*.mlz             # two previously-exported project archives
│   ├── exports/*.xlsx             # one previously-generated Excel export
│   └── uploads/
│
└── studies/                       # 40K — two committed .mlz sample archives + a README
    ├── README.md
    ├── maggi-malaysia.mlz
    └── maggi-malaysia-2026.mlz
```

Collapsed/not walked file-by-file: `.venv/` (349M, standard pip-installed packages — see §2 for
the versions actually resolved), `.git/` (2.1M, walked via `git log`, not via raw object
inspection), `__pycache__/` and `.pytest_cache/` (build/test artifacts, no source information).

## 2. Languages, frameworks, libraries

**Language:** Python only, both backend and tests. Frontend is hand-written vanilla JavaScript
(no TypeScript, no JSX, no build step) — confirmed by `static/app.js` containing plain
`function`/`async function` declarations and direct DOM calls (`document.querySelectorAll`,
`fetch`), with no `import`/`require` statements and no bundler config anywhere in the repo.

**Python version:** 3.13.5, per `.venv/pyvenv.cfg` (`version = 3.13.5`). `README.md` §"Quick
start" states "Python 3.11+" as the stated requirement (cite: `README.md`); the actual dev venv
is 3.13.

**Declared dependencies** (`requirements.txt`, minimum-version pins only — no `==` pins, no lock
file anywhere in the repo):
- Web: `fastapi>=0.110`, `uvicorn[standard]>=0.27`, `itsdangerous>=2.1`, `python-multipart>=0.0.9`
- HTTP/scraping: `requests>=2.31`, `beautifulsoup4>=4.12`, `lxml>=5.0`, `feedparser>=6.0`,
  `playwright>=1.42`
- Analysis/vision: `anthropic>=0.40`
- Trends: `pytrends>=4.9`
- Media: `Pillow>=10.0`
- Export: `openpyxl>=3.1`, `python-docx>=1.1`
- Config: `pyyaml>=6.0`, `python-dotenv>=1.0` (optional — `settings.py` has "a built-in fallback
  loader" per the file's own comment)
- Testing: `pytest>=8.0`, `httpx>=0.27` (FastAPI `TestClient` dependency)

**Actually-resolved versions in `.venv`** (`pip freeze`, same machine): `fastapi==0.139.2`,
`uvicorn==0.51.0`, `anthropic==0.119.0`, `playwright==1.61.0`, `pytrends==4.9.2`,
`requests==2.34.2`, `beautifulsoup4==4.15.0`, `lxml==6.1.1`, `feedparser==6.0.12`,
`openpyxl==3.1.5`, `python-docx==1.2.0`, `PyYAML==6.0.3`, `pytest==9.1.1`, `httpx==0.28.1`.

**Discrepancy worth recording (fact, not a fix suggestion):** `Dockerfile` pins its base image
to `mcr.microsoft.com/playwright/python:v1.42.0-jammy` (cite: `Dockerfile` line 4), i.e. Playwright
1.42, while the locally-resolved dev venv has `playwright==1.61.0`. With no lock file constraining
either environment, the Docker image and a local `pip install -r requirements.txt` can resolve to
different Playwright (and other library) versions on different days, since every dependency in
`requirements.txt` is a floor (`>=`), not a pin.

**No package.json / go.mod / Cargo.toml** — confirmed by `find` returning none of these; this is a
single-language (Python) repository with a plain-JS static frontend that has no dependency
manifest of its own (no CDN `<script>` tags in `static/index.html` either — UNKNOWN was not
needed here, directly confirmed by reading the file: it contains no `<script src="http...">`
tags, only `<script src="/static/app.js">`).

## 3. Entry points

- **Primary app process:** `python app.py` → `app.py`'s `if __name__ == "__main__": main()` →
  `main()` calls `uvicorn.run("app:app", host=settings.host, port=settings.port, reload=False)`
  (cite: `app.py`, final ~15 lines).
- **Docker:** `Dockerfile`'s `CMD ["python", "app.py"]` — same entry point as above, inside the
  `mcr.microsoft.com/playwright/python:v1.42.0-jammy` base image.
- **docker-compose:** `docker-compose.yml` builds from the local `Dockerfile` (`build: .`) and
  runs the one `marketlens` service; no other services (no separate DB, queue, or worker
  container) are declared.
- **Non-Docker setup:** `setup.sh` (macOS/Linux) / `setup.bat` (Windows) create the venv, install
  `requirements.txt`, run `python -m playwright install chromium`, and copy `.env.example` to
  `.env` if absent. They print the run command (`python app.py`) but do not run the app
  themselves.
- **Demo data:** `seed_demo.py` is a separate, manually-run script (`python seed_demo.py`) that
  populates one demo project; it is not invoked by `app.py` or any startup hook.
- **No `Procfile`, no `package.json` scripts section, no `manage.py`-style CLI, no separate worker
  process/entry point** — confirmed absent by `find`. Background job processing (see
  `jobs.py`) runs inside the same `app.py` process, not a separate worker.

## 4. Top-level modules/packages — one sentence each, from contents (not names)

| Module | What it appears to do, based on its actual contents |
|---|---|
| `app.py` | Defines every FastAPI route (`@app.get`/`@app.post`/`@app.put`/`@app.delete`), the `require_user` auth dependency, a cache-control middleware, and app startup (`lifespan`) that runs migrations and starts the scheduler. |
| `settings.py` | Reads all configuration from environment variables into one `settings` object (mode, host/port, data dir, API keys, HTTP politeness numbers), with a fallback `.env` line-parser if `python-dotenv` isn't installed. |
| `config.py` | The largest single-purpose module (661 lines): turns raw wizard intake into a full project config dict — country/language reference tables, Google/Bing News URL builders with date-range chunking, keyword-structure scaffolding, and `regenerate_news_feeds()`. |
| `storage.py` | All SQLite reads/writes via the stdlib `sqlite3` module directly (no ORM) — project CRUD, item de-dup by content hash, near-duplicate clustering, run/job bookkeeping, user table, audit log. |
| `migrations.py` | A list of ordered Python functions (`_m001_initial`, `_m002_story_clusters`) applied against `PRAGMA user_version`, run once at startup. |
| `jobs.py` | An in-process, single-writer job queue (a Python list/dict guarded by a lock, not a broker) that runs one collection job at a time in a background thread. |
| `http_client.py` | One shared `requests.Session` factory with a `urllib3.util.Retry` policy and a simple per-domain delay mechanism. |
| `analysis.py` | Batches un-tagged collected items (12 at a time) into a single Claude prompt asking for sentiment/summary/purchase-driver/brand-focus tags, parses the JSON reply, writes tags back to SQLite. |
| `analytics.py` | Read-only SQL aggregation functions (sentiment by channel, brand vs. competitor, purchase drivers, trend volume, verbatim examples) consumed by the dashboard and Excel export. |
| `source_discovery.py` | Sends the project's market/category to Claude asking for real candidate news/e-commerce/forum/subreddit sources, then validates each candidate against the live network (feed-health check, reachability probe) before returning it. |
| `term_expansion.py` | Sends a single keyword to Claude asking for product-variant phrases, real brand names, and per-language translations, returns them as review candidates; a separate function turns a *confirmed* selection into new keyword-structure entries. |
| `market_intel.py` | CRUD for user-entered "market fact" records that must each carry a citation (source name/URL/date) before being stored. |
| `export.py` | Builds a multi-tab `.xlsx` workbook (openpyxl) from a project's stored items/analysis/runs — Summary, Methodology, Confidence, per-channel tabs, an "All Items" combined tab. |
| `report.py` | Assembles a Markdown "five pillar" narrative report and can render it to `.docx` via `python-docx`. |
| `archive.py` | Zips/unzips a project's config + items + analysis + run log into a portable `.mlz` file for transfer between instances. |
| `auth.py` | Cookie-session login/logout/current-user helpers, only enforced when `MODE=team`. |
| `scheduler.py` | A `while True: sleep(...)` loop (background thread) that checks a `schedules` table for due recurring collection jobs and enqueues them via `jobs.py`. |
| `seed_demo.py` | One-shot script that calls `config.run_wizard()` + `storage` functions directly to create a fictional "Acme Cola" project with hand-written fixture items. |
| `scrapers/__init__.py` | A dict (`CHANNEL_INFO`) describing each of the 10 channels (method, limitation text) plus a `collect(channel_name, ...)` dispatcher that imports and calls the matching `scrapers.<name>.collect()`. |
| `scrapers/base.py` | A small `ScrapeResult` helper class (accumulates items + error strings + a diagnostics dict) and `relevance_terms(cfg)`, used by every channel module. |
| `scrapers/relevance.py` | HTML boilerplate/nav/related-links stripping plus term-presence checks (`contains_any_term`, `term_appears_anywhere`) used to gate whether a fetched page counts as relevant. |
| `scrapers/news.py` | The largest scraper (495 lines): builds/consumes Google News and Bing News RSS search feeds plus arbitrary direct RSS feeds, date-chunks Google News queries, resolves Google's redirect URLs, applies the market-relevance gate, stores items. |
| `scrapers/gdelt.py` | Queries GDELT's public DOC 2.0 JSON API for a date-chunked keyword search and re-validates each returned title against the project's relevance terms before storing. |
| `scrapers/reddit.py` | Fetches subreddit `new.rss`/`top.rss`/`search.rss` and per-post `.rss` comment feeds over plain HTTP (no OAuth), with its own 429-retry wrapper. |
| `scrapers/forums.py` | Fetches a user-supplied forum thread URL with `requests`, extracts post bodies with a ranked list of CSS selectors, and follows "next page" links by matching localized link text. |
| `scrapers/quora.py` | Fetches a user-supplied Quora URL with `requests` and classifies the response as blocked (Cloudflare/CAPTCHA/login-wall) vs. usable before extracting any text. |
| `scrapers/ecommerce.py` | Drives headless Chromium via Playwright to open user-supplied marketplace URLs, intercepts XHR responses that look like review APIs, and runs bot-block/CAPTCHA heuristics on the rendered page before storing anything. |
| `scrapers/youtube.py` | Calls the official YouTube Data API v3 `search`/`commentThreads` endpoints; a no-op (skips, does not fabricate) if `YOUTUBE_API_KEY` is unset. |
| `scrapers/google_business.py` | Calls the official Google Places API to look up a business and pull its reviews; same no-op-if-unset pattern. |
| `scrapers/trends.py` | Wraps `pytrends.request.TrendReq` for interest-over-time + related queries, with an app-level retry loop written because pytrends's own retry args crash under the installed `urllib3` version. |
| `scrapers/image_analysis.py` | Sends already-collected image URLs to a Claude vision-capable model for a description/classification, storing the result as a new item row. |

## 5. Files opened/inspected vs. not opened

**Opened and read (fully or in the specific sections cited) during this audit:** `app.py`,
`config.py` (partial — cross-referenced from earlier session work, re-confirmed live for this
audit), `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `setup.sh`, `.env.example`,
`.env` (key names + value lengths only, values never printed), `.gitignore`, `.claude/settings.json`,
`version.py`, `migrations.py` (function names), `README.md` (headings), full `git log`.

**Exist but were NOT opened in this phase** (line-count/structural inspection only so far; full
content review is deferred to Phases 1–4 where each is in scope): `storage.py`, `jobs.py`,
`http_client.py`, `analysis.py`, `analytics.py`, `source_discovery.py`, `term_expansion.py`,
`market_intel.py`, `export.py`, `report.py`, `archive.py`, `auth.py`, `scheduler.py`,
`seed_demo.py`, every file under `scrapers/`, `static/app.js`, `static/index.html`,
`static/style.css`, every file under `tests/`.

**Not opened at all, out of scope for a code audit:** `.venv/**` (349M of vendored third-party
package source — not this repository's own code), `__pycache__/**`, `.pytest_cache/**`, `.git`'s
internal object store (inspected only via `git log`/`git show`, not raw object bytes), `.DS_Store`
(macOS Finder metadata, binary, no code content), the two `.mlz` files under `studies/` and the
`.mlz`/`.xlsx` files under `data/` (binary zip/xlsx archives — their *existence and file sizes*
are recorded above; their internal contents were not extracted in this phase).

## 6. Presence/absence checklist

| Item | Present? | Evidence |
|---|---|---|
| Automated tests | **Yes** | `tests/` — 26 files, 3020 lines, `pytest`-based; `python -m pytest -q` run during this audit reports `162 passed, 1 warning in 1.38s` |
| CI config (GitHub Actions etc.) | **No** | No `.github/` directory anywhere in the tree; no `.gitlab-ci.yml`, `.circleci/`, `azure-pipelines.yml`, or similar found |
| Dockerfile | **Yes** | `Dockerfile` (repo root) |
| docker-compose | **Yes** | `docker-compose.yml` (repo root), one service |
| IaC (Terraform/CDK/Pulumi/etc.) | **No** | None found by `find` |
| `.env` file | **Yes** | Present at repo root; gitignored (`.gitignore` line `.env`); confirmed never committed via `git log --all --full-history -- .env` (empty result) |
| `.env.example` | **Yes** | Repo root, documents every recognized env var |
| README / docs | **Yes** | `README.md` (268+ lines, product-facing), `CLAUDE.md` + `HANDOFF.md` (engineering/session-continuation docs, not end-user docs) |
| Database migration files | **Yes** | `migrations.py` — 2 migrations defined (`_m001_initial`, `_m002_story_clusters`) applied via `PRAGMA user_version`, not a separate migrations directory/tool (no Alembic, no raw `.sql` files) |
| Lock file (pinned exact dependency versions) | **No** | No `requirements.lock`, `Pipfile.lock`, or `poetry.lock`; `requirements.txt` uses `>=` only |
| Separate worker/queue process | **No** | Job execution happens in a background thread inside the same `app.py` process (`jobs.py`); no Celery/RQ/separate worker entry point |

## 7. Git history scan

- **Commit count:** 31 (all on `main`; single remote `origin` → `https://github.com/ashwinsharma89/Scraper.git`; no other branches).
- **Date range:** `2026-07-25` (initial commit) → `2026-09-13` (latest, at time of this audit).
- **Initial commit** (`544324e`, `2026-07-25`) already contains the full application — its own
  message states: "Local-first market/product intelligence app: FastAPI + SQLite (WAL) backend,
  vanilla-JS SPA, 10 Tier-1 scrapers with strict relevance validation, Claude analysis, cited
  market-intel + manual-intel, Excel/Word/Markdown export, team mode, scheduler, AI source
  discovery, and a news market filter... a 69-test suite." I.e. the repository's git history does
  **not** show incremental early development — it starts from an already-complete first version.
- **Subsequent 30 commits** are a mix of: (a) real feature additions after the initial commit —
  one-click "Extensive research" (`a852d9a`), portable `.mlz` archives (`278bb88`, `ff30f7e`), (b) a
  named batch of "structural gap" fixes (`ca628fd`, `6455b3f`, `10cac1b`, `bd26e9d` — syndication
  clustering, demonym false-negatives, paraphrase relevance, a second news index), (c) a named
  batch of live-testing-driven channel fixes (`aceb1e5`, `b4cf5b1`, `4d3136d`, `40797d8`, `9dc537a`,
  `8aba8ed` — GDELT noise, Reddit's JSON API being dead, Forums selector quality, pytrends's
  broken retry, Quora/E-commerce bot-block handling), and (d) the most recent stretch — UI dropdown
  rework, a stale-cache bug fix, a market-filter native-script fix, and the newest feature
  (`e16cc79`, AI term expansion).
- **No merge commits** — every commit is a fast-forward on `main` (linear history, single author
  per `git log`, co-authored by an AI assistant per every commit trailer).
- **Keyword scan of commit messages** for "fix / workaround / hack / todo / temporary": 15 of the
  31 commits contain "Fix" (list reproduced above under §"commit messages" — every one describes a
  *root-caused* bug fix with an explanatory message, not a stopgap); zero commits contain
  "workaround", "hack", "todo", or "temporary" in their subject line.
- **In-code markers:** a repo-wide search for `TODO`, `FIXME`, `HACK`, `XXX` across all `.py` files
  (excluding `.venv` and `tests/`) returned **zero matches**.
- **No PR descriptions to review** — the repository has no pull-request history (single-branch,
  direct-to-`main` commits only, per `git log --all` showing no merge commits and `git branch -a`
  showing no other branches).

---

## Open questions for Phase 1

1. `app.py` is 676 lines and defines every route directly (no router modules) — is responsibility
   cleanly separated by concern within that one file, or mixed?
2. `scrapers/__init__.py`'s `CHANNEL_INFO`/dispatcher — what exactly is the contract each
   `scrapers.<name>.collect()` function must satisfy, and is it enforced anywhere (type checking,
   a base class, a test) or only by convention?
3. `jobs.py` is described as "single-writer" — what specifically is serialized (DB writes only, or
   the whole collection run), and what happens to a second job request while one is running?
4. Migration file `_m001_initial` — does it define the full schema in one function, and does that
   match what `storage.py` actually queries against (any drift)?
5. `static/app.js` at 1102 lines with no framework — is there an internal structure (sections,
   naming convention) that amounts to a de facto architecture, or is it one flat script?
