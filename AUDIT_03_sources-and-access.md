# AUDIT_03 — Source-by-Source, Rate Limiting/Anti-Bot, Proxy/IP

Reads AUDIT_00–02 as prior context. Every row below is from the actually-implemented
`scrapers/<name>.py collect()` function, not from `CHANNEL_INFO` text alone (which AUDIT_01
already flagged as stale for at least one channel — cross-checked per row below).

---

## Section 1 — Source-by-source audit

| Source | Access Method | Type | Discovery | Fetching | Pagination | Auth | Rate-limit handling | Retry logic | Proxy | Browser automation | Content extraction | Metadata | Dedup | Historical data | Known limitations | Files |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **News (Google News RSS)** | Search-feed URL, `hl/gl/ceid` params | Search index (RSS) | `source_plan.google_news_feeds` (config-generated, one per language+structure) | `http_client` shared session | Date-range chunking (`chunk_date_ranges`) works around the ~100/query cap; no page-token pagination | None | Shared `http_client` retry (429/5xx, `backoff_factor=0.5`) + per-domain rate limiter | urllib3 `Retry(total=settings.http_retries)` on the shared session | None | No | Title/RSS-summary; body fetch optional (`fetch_bodies` param) via redirect resolution | outlet domain, language, structure, published date | project-scoped `content_hash` in `storage.py` | Yes, via date-chunking (only chunkable index) | Article body text is the encrypted-URL-obfuscated Google redirect unless resolved; ~100-results/query is an external Google-side cap, not adjustable in code | `scrapers/news.py`, `config.py` (feed builders) |
| **News (Bing News RSS)** | Search-feed URL, `setmkt` param | Search index (RSS) | `source_plan.bing_news_feeds` | same shared session | **No date-range operator** — one query per collection, not chunked (confirmed: `config.build_bing_news_url` has no `after`/`before` param, unlike its Google counterpart) | None | Same shared retry/rate-limiter | Same | None | No | Real first-paragraph text (Bing's redirect resolves normally, unlike Google's) | Same as above | Same | **No** — cannot be chunked by date at all | Thinner coverage for some queries/markets than Google (observed live this session: 0 entries returned for several markets where Google had 100) | `scrapers/news.py`, `config.py` |
| **News (direct RSS)** | User-pasted feed URL | RSS | User-configured list (`source_plan.rss_feeds`) — zero auto-discovery | Same session | Whatever the feed itself provides (typically none) | None | Same | Same | None | No | Feed's own `<description>` — real first-paragraph text per module docstring | Outlet domain, published date | Same | No | Depends entirely on the specific feed's own retention window | `scrapers/news.py` |
| **GDELT** | DOC 2.0 JSON API | Hosted search API | One query, date-chunked | Same session | `maxrecords` per chunk, code-default 250 (`scrapers/gdelt.py` line 89, overridable via `collection_settings.gdelt_chunk_size`) | None | Same shared retry/rate-limiter | Same | None | No | Title/link/date/outlet/language **only — no article body** (per `CHANNEL_INFO`, confirmed: `scrapers/gdelt.py` does not fetch article pages) | outlet, language, date | Same | Yes, monthly chunking | Metadata-only; own relevance matching is loose, re-validated against project's `relevance_terms` before storing (per prior session work, re-confirmed: `scrapers/gdelt.py` calls a title-match check before `result.add`) | `scrapers/gdelt.py` |
| **Reddit** | `.rss` (Atom) endpoints — **not** the JSON API | Public unauthenticated feed | Configured subreddits × `new.rss`/`top.rss?t=year`/`search.rss?q=<relevance_terms>` | Same session, `UA` header override, custom `rate_delay=RATE_DELAY` (6.0s, `scrapers/reddit.py` line 43) | No page-token pagination; comments fetched per-post via `{permalink}.rss` for a capped number of top posts | None (no OAuth) | **Two layers**: (1) `http_client`'s generic 429/5xx retry, (2) Reddit-specific `_fetch_with_429_retry` wrapper (line 134) with its own `RETRY_429_WAIT=20.0`s, `RETRY_429_ATTEMPTS=2` (lines 44-45) | Both layers active simultaneously — see Section 2 for how they compose | None | No | Post title/selftext + top-N posts' comments; explicit `is_deleted()` filter | subreddit, author (if present), published date | Same | No — RSS has no historical backfill | **`CHANNEL_INFO` in `scrapers/__init__.py` (lines 57-60) is stale**: describes this channel as "public JSON"/"Public JSON only, no API key" — the actual code exclusively uses `.rss`, and the module's own docstring (line 3) states the `.json` endpoint is dead since Reddit's 2023 anti-scraping crackdown. Live-verified this session: Reddit's rate limit is "much tighter than a typical API" (`http_client.py` line 74's own comment) and this sandbox's aggressive same-session testing repeatedly tripped 429s across multiple subreddits at once | `scrapers/reddit.py`, `http_client.py` |
| **Forums** | User-pasted thread/listing URL | Generic HTML scrape | **Zero discovery** — user supplies every URL; only in-thread "next page" link-following (multi-language label matching) | Same session | `page_cap`, code-default 10 (`scrapers/forums.py` line 144, `config.py` line 578) | None | Generic `http_client` retry/rate-limiter only — no forum-specific extra layer | Generic only | None | No | Ranked CSS-selector post-body extraction (scored by average matched-text length, per prior session's fix for chrome-vs-content selector quality) | thread URL, page number | Same | No | Post structure varies per forum; a custom selector may be needed; no crawling beyond the given thread | `scrapers/forums.py` |
| **Quora** | User-pasted question-page URL | Generic HTML scrape | Zero discovery — user-supplied URLs only | Same session | None | None | Generic only | Generic only | None | No | Same relevance validation as News, when not blocked | question URL | Same | No | **Universally, deterministically blocked**: `_CLOUDFLARE_MARKERS` (line 29) detects Cloudflare's managed JS challenge; live-verified this session as present on every request across all tested URLs/User-Agents. This is a detection-and-report mechanism, not a bypass — the channel is documented (and confirmed) to return nothing in practice | `scrapers/quora.py` |
| **E-commerce** | User-pasted product/search URL, or `{q}`-template × keywords | Rendered-browser scrape | `build_search_urls()` (line 129) expands templates against `relevance_terms`/configured keywords — no discovery beyond that | **Playwright-driven Chromium, NOT `http_client`** — a structurally separate fetch path from every other channel | None (single-page snapshot semantics; scheduled repeats build a time series, no backfill) | None | **No rate-limiting or retry at all for the Playwright path** — confirmed: `scrapers/ecommerce.py`'s `collect()` calls `page.goto()` directly with only a `timeout_ms` (code-default 30000ms, line 192), no retry wrapper, no per-domain delay | Only Playwright's own default navigation timeout behavior (a single attempt, no retry-on-failure loop in this code) | **Per-run only, single static proxy string** — `params.get("proxy")` (line 191) passed to `browser.launch(proxy={"server": proxy})` (line 199) if set. **This configuration path exists but is not exposed anywhere in the frontend** (`static/app.js`/`static/index.html` contain zero references to "proxy") and has zero test coverage (`tests/test_ecommerce.py` contains zero references to "proxy") — a real, verified case of "configured in code, not used in the actual product surface" | **Yes — Playwright/Chromium**, the only channel that renders JS | Rendered page text; internal review-API XHR interception (`looks_like_review_endpoint`) | product/search URL, price (regex-extracted), image URLs | Same | No | **Two distinct, live-verified bot-blocks**: Shopee returns a soft bot-wall on every headless request (text-marker detected via `_looks_blocked`'s `_BLOCK_MARKERS`); Lazada's product-detail data is gated by a CAPTCHA at the underlying API level (`_CAPTCHA_HTML_MARKERS`, line 75, checks raw HTML for `recaptcha`/`hcaptcha`/etc. widget markers not visible via `inner_text`) — both confirmed this session with real captured page content, not assumed | `scrapers/ecommerce.py` |
| **YouTube** | Official Data API v3 | Official API | `search.list` by keyword + `regionCode`/`relevanceLanguage` | Same session (an API call, not a scrape) | `maxResults=min(max_videos, 50)` (line 53); `max_videos` code-default 25 (line 50); comments paginated via `pageToken` up to `maxResults=100` per page (line 92-95) | **API key** (`YOUTUBE_API_KEY`) — channel is a documented no-op (skips, does not fabricate) if unset | Generic `http_client` retry only | Generic only | None | No | Video snippet + full comment threads | video id, channel, published date | Same | Bounded by API quota, not by this code | Requires an API key; Google's quota system applies (external, not enforced in this code) | `scrapers/youtube.py` |
| **Google Business (Places)** | Official Places API | Official API | Text-search by brand+market | Same session | UNKNOWN — no explicit page-size parameter found in `scrapers/google_business.py`; Google Places' own API caps reviews per place at a fixed number by design, but that is an external API behavior this audit did not find a corresponding code-level parameter for (requires a live API response to confirm exactly, not determinable from static code alone) | **API key** (`GOOGLE_PLACES_API_KEY`) — same no-op-if-unset pattern | Generic only | Generic only | None | No | Place details + reviews | place id, review rating/date | Same | Bounded by API, not this code | Requires an API key; "Places returns a capped sample of reviews" (`CHANNEL_INFO`, not independently re-verified against a live call in this phase — flagged for Phase 5/6 as UNKNOWN pending a real API test) | `scrapers/google_business.py` |
| **Google Trends (pytrends)** | Unofficial `pytrends` wrapper around Google's internal Trends API | Unofficial/reverse-engineered API | Fixed configured keyword list | Same session, via `pytrends.request.TrendReq` (not `http_client` directly — `pytrends` manages its own HTTP internally) | `keywords[:5]` — hard code-level cap of 5 terms per request (line 57), a pytrends/Trends API constraint | None | **Custom retry wrapper** (`_call_with_retry`, line 29) — `RETRY_WAIT=20.0`s, `RETRY_ATTEMPTS=2` (lines 25-26), written specifically because pytrends' own `retries=`/`backoff_factor=` constructor args crash under the installed `urllib3` version (per this module's own docstring, corroborating prior session findings) | Custom only (pytrends' native retry is unusable) | None | No | Interest-over-time (relative index, 0-100) + related queries | keyword, date | N/A — a numeric series, not discrete items in the same sense | N/A | Relative index only, never absolute search volume (documented, and enforced by what the API itself returns — not a code choice) | `scrapers/trends.py` |
| **Image analysis** | Derived — Claude vision over already-collected image URLs | N/A (not a web source) | Image URLs gathered from prior E-commerce results (`jobs._gather_ecommerce_images`) | Anthropic SDK (vision-capable model) | N/A | `ANTHROPIC_API_KEY` | Whatever the `anthropic` SDK's own client does internally — **UNKNOWN, not inspected in this phase** (deferred to AUDIT_04, which explicitly scopes all AI/LLM usage) | UNKNOWN, same reason | N/A | No | EXIF (Pillow) + Claude's description/classification | source image URL | Same | N/A | Only runs on images the E-commerce channel already collected — cannot run standalone | `scrapers/image_analysis.py` |

**Note on `CHANNEL_INFO` accuracy, generalized from Section 1's per-row cross-check:** beyond the
confirmed Reddit mismatch (AUDIT_01), the method/limitation text for GDELT, Forums, YouTube,
Trends, and E-commerce was checked against each channel's actual current code during this phase
and **found consistent** with what the code does. Quora's `CHANNEL_INFO` text was also confirmed
accurate against `scrapers/quora.py`'s actual Cloudflare-detection logic. Google Business's
"capped sample of reviews" claim could not be independently verified against a live API response
in this static-inspection phase (see the UNKNOWN in that row).

---

## Section 2 — Rate limiting / anti-bot analysis

| Mechanism | Implemented? | Evidence |
|---|---|---|
| 429/403 handling | **Yes, layered** | `http_client.py`'s `Retry(status_forcelist=(429, 500, 502, 503, 504), ...)` (lines 67-80) applies to every channel except E-commerce (Playwright bypasses `http_client` entirely). Reddit and Trends each add a **second**, channel-specific retry layer on top (`scrapers/reddit.py _fetch_with_429_retry`, `scrapers/trends.py _call_with_retry`) — written because their respective APIs' own native retry mechanisms were found broken or insufficient (Trends: pytrends' own retry args crash under the installed urllib3; Reddit: its rate limit is tighter than the generic policy tolerates, per `http_client.py` line 74's comment) |
| CAPTCHA / Cloudflare / bot-challenge detection | **Yes, for Quora and E-commerce specifically** | `scrapers/quora.py`'s `_CLOUDFLARE_MARKERS`/`_cloudflare_challenge` (lines 29-41); `scrapers/ecommerce.py`'s `_BLOCK_MARKERS` (text-based) + `_CAPTCHA_HTML_MARKERS` (line 75, raw-HTML-based, catches modal/iframe challenges invisible to `inner_text`). **No such detection exists for News/GDELT/Reddit/Forums/YouTube/Google Business/Trends** — those channels rely solely on HTTP status codes, not content-based block detection (a 200 response with blocked content in those channels would not be specifically flagged as a bot-challenge, only as whatever downstream relevance/parsing failure it happens to cause) |
| Exponential backoff | **Yes, generic layer** | `backoff_factor=0.5` in `http_client.py`'s `Retry` config — standard urllib3 exponential backoff formula applies automatically on the retries `Retry` itself performs |
| Jitter | **UNKNOWN / likely absent** | `urllib3.util.retry.Retry`'s default backoff does not add jitter unless explicitly configured; no jitter parameter is passed in `http_client.py`'s `Retry(...)` call — confirmed absent from the constructor call, though a definitive "does urllib3 add any jitter by default in the installed version" would need a runtime check of the exact urllib3 version's source, not asserted here |
| Per-domain throttling | **Yes** | `http_client.py`'s `_DomainRateLimiter` (lines 17-39) — keyed by `urlparse(url).netloc`, blocks so no single domain is hit more often than `delay` seconds (`settings.rate_limit_seconds`, default from `.env.example`: `1.5`) |
| Concurrency limits | **Trivially yes, by architecture, not by explicit limit** | Only one job runs at a time system-wide (`jobs.py`'s single worker thread, per AUDIT_01 Section 3.7) — there is no scenario in this codebase where two scrapers fetch concurrently from the same process, so no explicit concurrency-limit config is needed or present |
| Request pacing | **Yes** | Same `_DomainRateLimiter`, plus Reddit's explicit `RATE_DELAY=6.0`s override (`scrapers/reddit.py` line 43) passed as `rate_delay=RATE_DELAY` on every Reddit request |
| Session management / cookies | **Minimal** | `requests.Session()` (one shared instance) persists cookies naturally across requests to the same host within a run, but nothing in the code explicitly manages, inspects, or resets cookies |
| Browser fingerprints | **Only a static User-Agent header** | `http_client.py` line 85: `self._session.headers.update({"User-Agent": settings.user_agent})` — one fixed UA string for the whole session, no fingerprint rotation/randomization anywhere. `scrapers/reddit.py` additionally overrides with its own `UA` value on Reddit requests specifically (line 131) |
| Proxy / IP / User-Agent rotation | **No rotation anywhere.** A single static proxy string is *supported* (E-commerce only, per Section 1) but not rotated, not pooled, and not exposed in the UI | See Section 3 below |
| Connection reuse | **Yes** | One shared `requests.Session` singleton (`http_client.get_session()`, lines 106-112) reuses connections via `HTTPAdapter` |
| DNS behavior | **Not specially handled** — default `requests`/OS resolver behavior, no custom DNS/resolver code found anywhere | N/A |
| Circuit breakers | **No** | No circuit-breaker pattern (tracking consecutive failures per domain and short-circuiting future calls) exists anywhere in `http_client.py` or any scraper — confirmed by the absence of any failure-counting state beyond the stateless per-call `Retry` object |
| Retry budgets (a global cap on retries across a whole run, not just per-request) | **No** | Retries are scoped per HTTP request only (`Retry(total=...)`); there is no run-level or job-level retry budget that could, for example, abort a whole job after N cumulative failures across many URLs |

**This audit does not recommend or describe any bypass of the above access controls** — per the
ground rules, Quora's Cloudflare challenge and the E-commerce bot-walls are documented as detected
outcomes, not as targets for evasion; the code itself contains no evasion logic (confirmed: no
CAPTCHA-solving, no fingerprint-spoofing-beyond-a-static-UA-string, no proxy rotation to evade
IP-based blocks).

---

## Section 3 — Proxy / IP architecture

**What's actually used:** **effectively none, by default.** The only proxy capability in the
entire codebase is the single optional `proxy` parameter in `scrapers/ecommerce.py` (Section 1),
which — if a caller explicitly passes `params={"proxy": "<server>"}` to that one channel's
`collect()` — is forwarded verbatim to Playwright's `browser.launch(proxy={"server": proxy})`
call. Every other channel (News, GDELT, Reddit, Forums, Quora, YouTube, Google Business, Trends)
goes through `http_client.get_session()`, whose `RetryingSession.__init__` (lines 49-85) contains
**no `proxies=` argument, no environment-variable proxy lookup, and no proxy pool of any kind** —
confirmed by reading the full constructor.

- **Type:** none/static only — no datacenter/residential/rotating proxy pool, no VPN integration,
  no multi-IP/cloud-instance-rotation mechanism exists anywhere in the repository.
- **Where config enters the code:** exactly one place — the `proxy` key of the `params` dict
  passed into `scrapers.ecommerce.collect()` (`scrapers/ecommerce.py` line 191). There is no
  settings.py env var for it (`grep` of `settings.py` for "proxy" returns nothing), no `.env.example`
  entry for it, and no frontend field to set it (`static/app.js`/`static/index.html` both confirmed
  to contain zero references to "proxy").
- **Selection mechanism:** none (a single fixed string, if provided at all) — there is nothing to
  select between, since only one proxy value can ever be configured per collection run and no
  pool exists.
- **Rotation scope:** N/A — no rotation logic exists.
- **Failed-proxy tracking/removal:** N/A — no such state is kept anywhere.
- **Geographic selection:** N/A — whatever geography the one manually-supplied proxy server
  happens to be at; the code has no concept of choosing a proxy by target market.
- **Source-specific usage:** proxy support is scoped to E-commerce only, by construction (it is a
  parameter of that one `collect()` function's signature and nowhere else).
- **EXISTS vs. USED, explicitly distinguished (per the phase's own instruction):** the proxy
  parameter **exists** in `scrapers/ecommerce.py`'s code and would function if supplied
  programmatically, but is **not used** anywhere in the actual product surface today — no UI
  control sets it, no test exercises it, and `CHANNEL_INFO`'s own text ("proxy recommended beyond
  light use") is *advice to a future operator*, not a description of an active, wired-up feature.

---

## Open questions for Phase 4

1. Full dedup algorithm (`content_hash` computation, `cluster_id` assignment) — referenced
   throughout this phase as "the same" for every channel, but its exact behavior against
   cross-channel/cross-language/near-duplicate cases is AUDIT_04's explicit scope, not yet traced.
2. Every AI/LLM call site (`analysis.py`, `source_discovery.py`, `term_expansion.py`,
   `scrapers/image_analysis.py`) — invocation frequency, token cost pattern (per-query vs.
   per-document), caching, and fallback behavior are all AUDIT_04 scope; this phase only
   confirmed which channels call Claude (Image analysis) versus which never do (all pure-fetch
   scrapers).
3. Google Business's actual per-place review cap — flagged UNKNOWN above; would need either a
   live API call/response inspection or the Google Places API's own published documentation
   (external to this repo) to resolve definitively.
4. Whether `_DomainRateLimiter`'s per-domain state (`self._last: Dict[str, float]`) is shared
   correctly across the single worker thread's sequential jobs (it should be, since it's a
   process-level singleton via `get_session()`) — worth a explicit note in Phase 5 since it means
   rate-limit state DOES persist across jobs within one process's lifetime, but resets to empty on
   every process restart (same class of issue as `jobs.py`'s in-memory job dict, AUDIT_01 Section
   1).
