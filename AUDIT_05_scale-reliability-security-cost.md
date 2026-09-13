# AUDIT_05 — Scale, Failure Modes, Observability, Security, Cost

Reads AUDIT_00–04 as prior context; builds directly on AUDIT_02's query-expansion findings and
AUDIT_03's per-source limit table rather than re-deriving them.

---

## Section 1 — Scale analysis

**Architecture-level ceiling, restated precisely from AUDIT_01/03:** exactly one background
thread (`jobs._worker_loop`) executes one `scraper.collect()` call at a time, system-wide, for
this one process. There are no concurrent workers, no distributed queue, no multi-process
scaling path — "requests/sec" or "concurrent workers" as a tunable does not apply, because the
number is fixed at 1 by the code, not by configuration.

**Per-run limits, consolidated from AUDIT_02/03 (not re-derived, cited again for this section's
completeness):**
- Google/Bing News: ~100 results/query/date-chunk (external, undocumented-as-a-code-constant,
  Google/Bing-side limit — `scrapers/news.py` line 6 comment, empirically confirmed live this
  session across many queries).
- GDELT: `maxrecords` code-default 250/chunk (`scrapers/gdelt.py` line 89).
- Google Trends: hard cap of 5 keywords/request (`scrapers/trends.py` line 57).
- YouTube: `max_videos` code-default 25, `maxResults` capped at 50 by the API itself
  (`scrapers/youtube.py` line 53).
- Reddit/Forums/Quora/E-commerce: no code-level page-count cap found beyond Forums'
  `page_cap=10` (`scrapers/forums.py` line 144); their real ceiling is whatever their respective
  listing/search endpoint naturally returns.
- Timeout that could kill a job before it reaches any of the above caps: E-commerce's
  `timeout_ms=30000` per page navigation (`scrapers/ecommerce.py` line 192) is the only explicit
  per-request timeout found; `settings.http_timeout` (env `HTTP_TIMEOUT`, default 30s per
  `.env.example`) applies to every `http_client`-routed request.

### Answering the specific ceiling question directly

**"What is the actual, current ceiling on results returned for a SINGLE query/job — hundreds, low
thousands, or genuinely 10,000-40,000+ in one run?"**

This must be split into two different numbers, because they are genuinely different questions:

1. **For ONE literal query term, in ONE language, on ONE channel:** the mechanical ceiling is
   **low thousands at the absolute maximum, realistically hundreds** — e.g. News: 1 feed × up to
   12 monthly chunks (a full year) × ~100 raw entries = **up to ~1,200 raw entries**, before the
   market-relevance gate removes a large fraction of them (empirically observed live this session
   on a real "coffee"/India query: 89-91% of raw entries were dropped as off-market for a generic,
   non-market-specific term) — leaving a **kept** count typically in the tens to low hundreds per
   feed per year, not thousands. This is a directly-cited, empirically-grounded number, not a
   guess: a real full-year single-term News run in this session returned `returned: 72` kept items
   from `~900` raw entries across 12 monthly Google News chunks + 1 Bing feed.

2. **Across MANY query variants × MANY languages × MULTIPLE channels for one project (i.e., after
   using `term_expansion.py` and running every channel):** the ceiling rises roughly linearly with
   the number of independently-capped feeds, since each new keyword *structure* (not just more
   terms in one structure — AUDIT_02 Section 1a step 5 is the load-bearing distinction here) adds
   its own ~100-per-chunk ceiling. **Empirically observed live this session:** applying a full
   term expansion (12 variants + 12 brands in English, 8 translated terms) took one real project
   from 1+1 to 87 Google+Bing News feeds — a **~44x increase in the number of independently-capped
   queries** for that one project. A full-year run across all 87×2 feeds was **not executed** in
   this session (only the smaller 15+15-feed and 1+1-feed stages were actually run to completion
   and measured) — so the exact resulting item count at 87+87 feeds is **UNKNOWN, not measured**;
   only the feed-count multiplier is confirmed.

**Direct answer: genuinely reaching 10,000-40,000+ results for what a user experiences as "one
search" is NOT achievable from a single literal query term against a single channel, under this
architecture, at any settings.** It becomes theoretically reachable only by (a) combining
many expanded query variants across many languages (via the opt-in `term_expansion.py` step,
which is a manual, per-term action a user must explicitly run and confirm — not something that
happens by typing one query) AND (b) running multiple channels, AND (c) the real world actually
containing that much matching content (a variable no code change controls). Whether 10k-40k is
achievable in aggregate this way for a real, saturated project is **UNKNOWN — requires an actual
full-scale multi-channel, fully-expanded run to measure**, since every number in this audit for
kept-item counts came from real content volume on real live queries, which varies by term,
market, and time window.

**Per-source breakdown of what happens first (rate-limit vs. cap vs. timeout) if you push volume
up, per channel** (drawing directly on AUDIT_03, not re-argued): News/Bing hit their external
~100/chunk cap first, worked around only by more chunks/more feeds, not by any retry; GDELT is
bounded by its own configurable `maxrecords`, effectively unbounded by rate limits within a
reasonable number of chunks; Reddit hits its **tighter-than-typical rate limit** first (confirmed
live, multiple 429s across several subreddits within one multi-channel run in this same session) —
of every channel, **Reddit is the one most likely to be blocked/throttled before any code-level
cap is reached**; Trends hits Google's own rate limit almost immediately under repeated same-IP
use (confirmed live: 429 on the very first request after prior same-session activity); E-commerce
hits **bot-detection blocks**, not rate limits, as its primary volume constraint (Shopee blocks
every request; Lazada's product-detail API returns an immediate CAPTCHA challenge even on a
never-before-touched product ID, confirmed live this session) — for E-commerce specifically,
blocking is not a function of request *volume* at all, it happens on the very first request in
some cases.

### AI/API cost efficiency at scale

**Restated precisely from AUDIT_04 Section 3, answering the specific question:** AI invocation is
**per-batch-of-12-items for the main analysis pipeline** (`analysis.py BATCH_SIZE=12`) — this is
**neither** "once per query" (cheap, query-count-bound) **nor** "once per document" (expensive,
document-count-bound) in the purest sense; it is closer to the cheap end, scaling as
`document_count / 12`, not `document_count`. The one call site that IS genuinely per-document is
`scrapers/image_analysis.py`'s vision call — one Claude call per image, uncached, cost scaling
**linearly with image count** (a much steeper cost curve than the main tagging pipeline, but
scoped only to E-commerce-collected images, which are a small subset of total items for most
projects). Term expansion and source discovery are each **one call per manual user action**,
totally decoupled from result volume — a user could run term expansion once and it would cost the
same one API call whether it's later used to generate 2 feeds or 87.

**Which happens first at scale — rate-limiting or cost?** Based on the above: **rate-limiting/
bot-blocking hits first, and hits per-source, well before AI cost becomes the binding constraint**
for the collection side of the pipeline — Reddit, Trends, and E-commerce all demonstrated
real-world blocking behavior in this session at volumes far below anything that would make the
12-items-per-call analysis pipeline expensive. The AI cost driver that scales worst is
**Image analysis** specifically, since it is genuinely one call per document — a project that
collected thousands of e-commerce images (itself unlikely, since E-commerce is one of the
most-blocked channels) would see AI cost scale linearly with that count, unlike every other AI
call site in the system.

---

## Section 2 — Failure modes

Traced with code citations from AUDIT_01/03/04; not re-explaining the mechanisms, only the
observable behavior at each named failure point.

| Failure | Actual behavior | Citation |
|---|---|---|
| External API fails (non-2xx after retries) | `http_client`'s `Retry` exhausts, `requests` raises or returns the error status; the calling scraper's own `try/except` (present per-feed/per-request in every channel checked) appends a string to `ScrapeResult.errors` and continues with whatever else it can fetch | `http_client.py`, per-channel `collect()` bodies |
| 403/429 returned | Handled at up to two layers depending on channel (generic `Retry(status_forcelist=(429,...))`, plus Reddit's/Trends' own additional wait-and-retry) — after all retries exhaust, the specific request is abandoned and recorded as an error string, **not** a job-level failure (the job still completes with partial results + errors) | `http_client.py` lines 67-80, `scrapers/reddit.py` lines 134-149, `scrapers/trends.py` lines 25-38 |
| Proxy fails | N/A for every channel except E-commerce (no proxy elsewhere, AUDIT_03 §3); for E-commerce, a bad `proxy` value would surface as a Playwright launch/navigation exception, caught by that channel's own `try/except` around `page.goto()` (confirmed structurally present, not traced line-by-line in this phase) | `scrapers/ecommerce.py` |
| DNS failure / connection timeout | Caught by the generic `except Exception` pattern present in every channel's per-request loop (confirmed present at the level checked in AUDIT_03), recorded as an error string; no special-cased DNS handling | `http_client.py`, per-channel |
| CAPTCHA encountered | **Detected and reported specifically for Quora and E-commerce only** (AUDIT_03 §2) — the run completes with an honest error message rather than storing blocked-page content as if it were real data (a deliberate, tested design principle per this session's own prior fixes: a real bug where Shopee's block page was once silently stored as a legitimate item was found and fixed). For every other channel, a CAPTCHA response (if one were ever served) would not be specifically recognized — it would most likely fail relevance/parsing checks and simply yield no usable content, or in the worst case pass through if it happened to contain matching text (**UNKNOWN — not tested against a real CAPTCHA response for those channels**) |
| JS fails (Playwright) | UNKNOWN — not traced in this phase; E-commerce is the only channel that executes JS at all, and this audit did not read its full exception-handling path around page script errors specifically (distinct from network/navigation errors, which are covered above) |
| Parser fails / malformed HTML / source changes structure | For Forums, this is explicitly acknowledged as a known limitation ("Post structure varies per forum; custom selector may be needed" — `CHANNEL_INFO`, confirmed consistent with actual scored-selector logic in AUDIT_03). A selector finding zero matches would yield zero items for that thread (not a crash), recorded implicitly by an empty result rather than an explicit "extraction failed" error — **UNKNOWN whether an explicit error is raised in the zero-match case or whether it silently returns nothing**, not traced to that level of detail in this phase |
| LLM call fails (any of the 4 call sites) | Analysis: the **whole 12-item batch** is abandoned, nothing written, items remain unanalyzed and are retried on the next manual "Analyze" click (`analysis.py` lines 154-157) — this is safe (no partial/corrupt writes) but means one bad batch blocks progress on those 12 items until manually retried. Source discovery / term expansion: the whole action fails with an HTTP 400 surfaced to the browser (`app.py`'s `except Exception: raise HTTPException(400, ...)` pattern, confirmed at both `api_suggest_sources` and `api_suggest_terms`) — no partial suggestions returned. Image analysis: **UNKNOWN**, flagged in AUDIT_04's open questions, not resolved in this phase |
| DB fails (SQLite locked/corrupt/disk full) | **UNKNOWN — not tested.** `storage.py` uses plain `sqlite3` connections via context managers (`write_conn()`/`get_conn()`); no explicit `sqlite3.OperationalError` (e.g. "database is locked") handling was found in `save_items()` or elsewhere during this phase's reads — a lock contention or disk-full event would most likely propagate as an unhandled exception up through `jobs._execute`'s outer `except Exception` (AUDIT_01 §3.7), marking that one job as errored, but this was not verified against an actual locked-DB condition |
| Worker crashes | The worker thread's own `_worker_loop` wraps `_execute(job_id)` in a `try/except Exception` that marks the specific job as `"error"` **without** killing the thread (`jobs.py` lines 48-61) — confirmed this is resilient to a single job's exception; a crash *inside* that except block itself, or a fatal interpreter-level error (not a Python exception), is outside what this pattern can catch, and was not tested |
| Job interrupted (process killed mid-run) | **Job-status history is lost** (the `_jobs` dict is process-memory only, confirmed AUDIT_01 §1) — a client polling `/api/jobs/{id}` for a job whose process died will get a 404 ("job not found") on restart, since `_jobs` starts empty. **However, any items already written via `storage.save_items()` before the interruption survive** (each `save_items()` call commits per the `write_conn()` context manager, and item-level dedup means a subsequent re-run of the same channel will not re-insert already-stored items) — so data is not lost, but **run bookkeeping for the interrupted run itself may be left in a `"running"` status forever** in the `runs` table, since `finish_run()` is only called if `run_collection()` returns normally or raises an exception it catches — an abrupt process kill (not a Python exception) skips that call entirely. This was directly observed as a real, repeated event in this session (the dev server process was killed and restarted multiple times) — **confirmed empirically**, not just inferred from reading the code |
| Process restarts | Migrations re-run (idempotent, `IF NOT EXISTS`/`ADD COLUMN` pattern, `migrations.py`) — safe. The job queue starts empty; the scheduler restarts its polling loop; `http_client`'s per-domain rate-limiter state resets to empty (AUDIT_03's open question #4) — meaning a channel that was mid-rate-limit-cooldown loses that cooldown memory on restart, potentially allowing an immediate re-request that a live process would have delayed |

**Whether jobs resume or lose progress, precisely: they do NOT resume; a killed job simply
disappears from job-status tracking, but the DATA it already wrote persists.** This is confirmed
by code inspection (Section above) and by this session's own repeated first-hand experience of
the exact scenario (server restarts leaving `/api/jobs/{id}` unable to find a previously-active
job, while the project's collected item count from that run's completed portion remained intact).

---

## Section 3 — Observability

**What is actually visible today when something breaks:**
- **No logging framework at all.** A repo-wide search for `import logging` or any `logger.*` call
  returns **zero matches** outside `.venv`. The only `print()` statements in non-test code (11
  total) are startup-banner messages (`app.py` lines 42-43) and `seed_demo.py`'s one-time console
  output — **none of them fire during normal scraper/job/analysis operation.**
- **What DOES persist, as a substitute for logs:** the `runs` table (`rows_returned`/`rows_new`/
  `rows_duplicate`/`errors_json`/`status` per collection run) and the `audit_log` table
  (`action`/`detail`/`acting_user` for project-level actions like `collection`, `project.create`,
  `terms.apply`) are both DB-persisted, queryable via `GET /api/projects/{pid}/runs` and
  `GET /api/projects/{pid}/audit`. This is a genuine, real observability mechanism for **what a
  collection run did and what errors it hit**, but it is not "logging" in the operational sense —
  there is no timestamp-by-timestamp trace of what the process was doing moment-to-moment, no way
  to tail live output, and nothing captured for the metrics below.
- **Metrics/dashboards/tracing:** **none exist.** No Prometheus/StatsD/OpenTelemetry integration,
  no `/metrics` endpoint, no APM agent — confirmed absent from `requirements.txt` and every file
  read in this audit.
- **Job status:** visible only while the process that ran it is alive (`GET /api/jobs/{id}`,
  `GET /api/jobs/active`) — in-memory only, per Section 2/AUDIT_01.
- **Per-source success rate, latency, error rate, rate-limit rate, extraction success:** **not
  tracked as first-class metrics anywhere.** The closest approximation is manually reading a
  specific run's `errors_json` text after the fact — there is no aggregated "Reddit has hit 429 in
  8 of the last 10 runs" view; a human would have to inspect each run's raw error strings
  individually via the Run Log UI tab.
- **Queue depth:** not exposed via any endpoint — `jobs.py`'s `_queue` (a stdlib `Queue`) has no
  size-reporting route.
- **Worker/DB health:** no explicit health-check beyond `GET /api/health`, which reports API-key
  presence and optional-dependency installation status (`app.py` lines 100-129) — it does **not**
  check DB connectivity, disk space, or worker-thread liveness.

**Plainly stated: when something breaks today, the only way to find out is to open the specific
project's Run Log or Audit tab in the UI (or query those two tables directly) and read the raw
error string a scraper wrote — there is no alerting, no aggregated error-rate view, and no
moment-to-moment log to tail.**

---

## Section 4 — Security

- **API keys / secrets:** loaded from environment variables only (`settings.py`), never
  hardcoded in source — confirmed by this audit's own repo-wide grep for common secret patterns
  finding nothing in tracked files, and `.env` (which does hold a real, redacted-in-this-audit
  Anthropic key locally) is correctly gitignored and confirmed never committed (AUDIT_00 §6/§7).
  **No hardcoded secrets found anywhere in the codebase.**
- **Password storage:** PBKDF2-HMAC-SHA256, 200,000 rounds, random 16-byte salt per user
  (`auth.py` lines 24, 31-34) — this is a sound, modern choice, not a weak/legacy hash.
- **Session secret:** read from `SESSION_SECRET` env var; if unset, falls back to a fresh random
  32-byte value generated at process start (`auth.py` lines 78-81) rather than an insecure blank
  or hardcoded default — the tradeoff (documented in-line) is that sessions won't survive a
  restart if the operator never set `SESSION_SECRET`, which is a reliability note, not a security
  weakness.
- **Auth/authz model:** `require_user()` (`app.py` line 70) is a no-op in `solo` mode (no auth at
  all, by design, for single-user local use) and enforces a signed-cookie session in `team` mode.
  Admin-only actions (creating users) explicitly check `acting["is_admin"]` (`app.py` lines
  156-158). **No role-based scoping beyond admin/non-admin exists** (e.g., no per-project access
  control in team mode — any authenticated team-mode user can access any project, confirmed by
  `_project_or_404()` taking no `user` parameter to check project ownership against).
- **SSRF risk — a real, precisely-locatable gap:** four distinct places accept an arbitrary,
  user-supplied URL and fetch it server-side with **no host/IP validation of any kind**: direct
  RSS feeds (`source_plan.rss_feeds`, consumed by `scrapers/news.py`), Forum thread URLs
  (`scrapers/forums.py`), Quora question URLs (`scrapers/quora.py`), and E-commerce product/search
  URLs (`scrapers/ecommerce.py`). None of these paths check the target host against a
  private-IP-range/localhost/link-local-metadata-address denylist before fetching — confirmed by
  the earlier grep across these files finding no such check anywhere, and by `http_client.py`'s
  `RetryingSession.get()` performing no URL/host inspection beyond `urlparse` for rate-limiter
  keying. **In `solo` mode this is a self-inflicted risk only** (a single local user pasting a URL
  for their own instance to fetch). **In `team` mode, any authenticated user could cause the
  server process to make an outbound request to an arbitrary internal address** (this audit
  documents the absence of a control, per the ground rules, and does not describe how to exploit
  it further).
- **Arbitrary URL fetching more broadly:** by product design, this is the entire point of several
  channels (a market-research scraper must fetch user-specified URLs) — the finding above is
  specifically about the *absence of any internal-network guard rail* on that inherent capability,
  not that the capability itself is a defect.
- **Command execution / injection risk:** no `subprocess`/`os.system`/`eval`/`exec` calls found in
  application code during this audit's reads (Playwright's own browser process management is the
  one subprocess-spawning dependency, invoked through its own SDK, not raw shell calls from this
  codebase). SQL is parameterized throughout every `storage.py` query read in this audit (`?`
  placeholders, not string interpolation) — no SQL-injection pattern found.
- **Exposed endpoints:** every `/api/*` route requires `require_user` except the handful of
  meta/auth routes (`/api/version`, `/api/mode`, `/api/auth/login`) which are appropriately
  public. `/api/health` explicitly reports only boolean key-presence, never values (line 118-121,
  self-documented in its own docstring) — this was independently verified true by reading its
  full body, not just its comment.
- **Logging of sensitive credentials:** since there is effectively no logging framework at all
  (Section 3), there is also no risk of a log line accidentally printing a secret — the flip side
  of the observability gap.
- **File-serving path traversal:** both download endpoints (`api_export_download`,
  `api_archive_download`) explicitly resolve the requested path and verify it lives under the
  correct base directory before serving (`app.py` lines 556-563, 630-636: `if
  settings.exports_dir.resolve() not in p.parents: raise HTTPException(400, "invalid path")`) —
  this is a correctly-implemented path-traversal guard, confirmed by reading the exact check, not
  assumed.

---

## Section 5 — Cost model

| Component | Cost driver | Notes |
|---|---|---|
| Search/News APIs (Google News, Bing News, GDELT) | **Free** — all three are public, unauthenticated endpoints (RSS/JSON), no API key, no billing relationship found anywhere in `settings.py`/`.env.example` for these three | The "cost" here is entirely rate-limit/blocking risk (Section 1), not monetary |
| Reddit | **Free** (unauthenticated `.rss`) | Same caveat — cost is availability risk, not money |
| YouTube Data API v3 | **Quota-based**, Google-side; this repo does not implement any quota-tracking/budget-alerting of its own | Relevant variable: `max_videos` per query (default 25) × comment-thread pagination — exact quota-unit cost is external to this repo, not determinable from code alone |
| Google Places API | **Per-request billing**, Google-side | Same — no in-repo cost tracking; relevant variable is number of place lookups + review-page fetches per run |
| Proxy/network | **None** — no proxy service is actually wired up (AUDIT_03 §3), so there is no proxy cost today despite `CHANNEL_INFO` recommending one for E-commerce at scale |
| Browser infra (Playwright/Chromium) | **Compute only** — runs the whole Chromium browser process on the SAME machine as the app (`scrapers/ecommerce.py` launches it directly, no separate browser-farm service); cost is CPU/memory on that one host, scaling with concurrent E-commerce jobs (which, per Section 1, is always exactly 1 at a time) |
| Cloud compute | **N/A as shipped** — this is a `python app.py` / single Docker container application with no cloud-specific deployment config (no Terraform/CDK per AUDIT_00 §6); cost model would be whatever the operator's own hosting choice costs, not something this repo defines |
| Database | **None** — SQLite is an embedded file, no separate DB service/billing | Storage cost is local disk only; `data/` measured at 2.2M in this repo (AUDIT_00 §1), trivial at current scale |
| Object storage | **None used** — exports/archives/uploads are stored on local disk under `data/`, not S3/GCS/etc. |
| LLM/API processing (Anthropic) | **Per-token, Anthropic-side billing** — the only real per-usage monetary cost driver in this entire system | Relevant variables, per AUDIT_04 Section 3: (a) `ceil(unanalyzed_items / 12)` calls for the main tagging pipeline, each with up to 12 items' title+text as input — cost scales sub-linearly with item count; (b) one call per image for Image analysis — cost scales linearly with image count, the steepest curve in the system; (c) one call per manual "Suggest sources"/"Expand a term" click — flat, decoupled from data volume entirely |
| Translation | **Folded into the term-expansion LLM call** — no separate translation API/service exists; translations are a field of the same `term_expansion.suggest_terms()` response, at no additional call |
| Monitoring | **None** — no paid or free monitoring/observability service is integrated (Section 3), so there is no monitoring cost line item today, but also no early-warning capability |

**Where exact pricing can't be determined, the relevant variables instead (per phase instruction),
consolidated:** total collection volume (items) and total run count are the two variables that
would drive Anthropic token cost at 100K/500K/1M/10M documents-analyzed scale, moderated by the
12-items-per-batch efficiency for standard analysis but NOT for Image analysis (linear). Given
Section 1's finding that **rate-limiting/blocking, not cost, is the first wall this architecture
hits** at scale, a realistic 100K-document scenario for this exact codebase would likely first
require solving the multi-channel/multi-feed volume problem (Section 1) — at which point the
dominant new cost, not modeled anywhere in this repo today, would be whatever number of parallel
IPs/proxies/browser instances are needed to sustain that volume without total blocking, which
this architecture has no mechanism for today (single worker thread, no proxy pool, AUDIT_03 §3).

---

## Open questions for Phase 6

1. A full quality rating (Excellent/Good/Adequate/Weak/Critical) per engineering dimension —
   this phase deliberately stopped short of assigning ratings, since Phase 6 is where synthesis
   and verdicts belong per the phase plan.
2. Whether the "no logging framework" gap (Section 3) is a genuine risk at this tool's actual
   scale (a single local operator watching their own runs) or only becomes one if/when it's
   deployed in `team` mode for multiple concurrent users — a judgment call for Phase 6/7, not
   resolved here.
3. The SSRF gap (Section 4) — severity depends heavily on deployment mode (`solo` vs `team`),
   which Phase 6's Missing Capabilities Matrix and Phase 7's business-fit answers should weigh
   explicitly rather than treat as a flat, context-free severity.
4. Whether reaching the 10,000-40,000 result range (Section 1) is a rate-limit problem, a cost
   problem, or a "the content doesn't exist" problem for any *specific* real term/market this
   tool might be pointed at — flagged throughout as requiring an actual saturated production run
   to measure, not answerable from static code alone.
