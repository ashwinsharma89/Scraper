# DESIGN_01 — Category-Aware, Multi-Vertical Source Discovery + New Frontend

**Status: PHASE A — design only. No implementation code accompanies this document, per the
ground rules. Do not begin Phase B until this is explicitly approved, and expect it to change —
Section 14 lists what's genuinely unresolved.**

Builds on AUDIT_00 through AUDIT_08 and the two features already shipped this session
(`term_expansion.py`, `outlet_discovery.py`) and the `market_signal()` word-boundary fix
(`scrapers/news.py`). Every citation below points at the actual current file/function; nothing
here re-derives what the audit already established.

---

## 1. Category taxonomy & classification

**Proposal: LLM classification, not a hardcoded list — for the same reason term expansion is
LLM-driven and not a static dictionary (AUDIT_02 §2).**

Today's only category concept is `product.category_type`, a **closed, hardcoded enum**:
`config.py` line 71, `CATEGORY_TYPES = ["fmcg_food", "consumer_electronics", "fashion",
"services", "b2b_industrial", "other"]`. This is exactly the kind of central-switch-statement
taxonomy the brief asks to move away from — every new vertical (healthcare, hyperlocal
food-and-events, etc.) would otherwise need a code change to this list and to every place that
branches on it (currently just `DELIVERY_APPLICABLE`/`segment_applicability`, config.py).

New module `category_discovery.py` (naming mirrors `term_expansion.py`/`outlet_discovery.py`):

```
classify_category(term, geo_scope, call_fn=None) -> {
    "category": str,            # free text, e.g. "coffee / food & beverage lifestyle"
    "confidence": float,        # 0-1, model's own self-reported confidence
    "reasoning": str,
    "structured_data_hint": Optional[str],  # e.g. "practitioner_directory" — see §6 caveat
}
```

The category is **free text returned by the model**, not selected from an enum — this is what
makes it extensible without a code change: asking about "doctors" returns "healthcare /
medical practitioners" today and would return whatever a genuinely new vertical is tomorrow,
with no central list to edit. `CATEGORY_TYPES` is not removed — it still drives the existing,
narrower `segment_applicability()`/delivery-channel logic, which is out of scope here — but it is
no longer the taxonomy this new pipeline uses.

**Confidence and the one place classification is NOT silent:** per §11, category classification
runs automatically — but if `confidence` is low, the wizard (step "a" in §12) shows the
classification for confirmation instead of proceeding silently. This is a conditional UI insertion,
not a universal manual gate, and it does not contradict Ground Rule #1 (that rule is about
*capabilities* being opt-in by default, not about surfacing a genuinely uncertain AI output for
a one-second human glance before spending API calls on a wrong category).

---

## 2. Category → source-type mapping

**Proposal: two layers, not one — an open-ended LLM layer for WHAT source types exist, and a
small, closed, code-level layer for HOW each gets operationalized.**

**Layer 1 (open, LLM-driven):** given the classified category + geo-scope, ask the model for
real, named source-type categories relevant to this vertical — the same "propose real things,
validate, let the user confirm" posture as `source_discovery.suggest_sources()` and
`outlet_discovery.suggest_outlets()`. For "coffee" this returns things like "lifestyle & food
blogs," "café/venue listing sites," "hyperlocal city guides"; for "doctors" it would return
"healthcare directories," "hospital/clinic sites," "medical news." This layer is genuinely
extensible — a new vertical needs no code change to produce a sensible list.

**Layer 2 (closed, code-level routing):** whatever source type Layer 1 names, the ACTUAL fetch
mechanism is bounded by a small, finite set of implementation strategies this tool can execute.
This is a legitimate, small enum — not a violation of the "no hardcoding" principle, the same
way `scrapers/__init__.py`'s `_REGISTRY` (10 named channels) is a legitimate closed set of
*implemented mechanisms*, not a hardcoded claim about the world. Proposed strategies:

| Strategy | When Layer 1 output maps to it | Existing code reused |
|---|---|---|
| `existing_channel` | The proposed source type IS one of today's 10 channels (Reddit, Forums, News, YouTube...) | The channel unchanged — `scrapers.get_scraper()` (`scrapers/__init__.py`) |
| `generic_site_discovery` | Everything else — lifestyle blogs, health directories, hyperlocal sites, any arbitrary editorial site | **New** — §4/§5 below |

A small classification call (or a simple keyword match against the 10 known channel names —
either is defensible; I'd start with the cheap keyword match and only add an LLM call here if it
proves unreliable, since this routing decision is low-stakes and easy to get right mechanically)
decides which row applies. Nothing about Layer 2 needs to change when a new vertical is added —
only `generic_site_discovery` ever needs to fire for a genuinely new kind of source, and it's
already generic by construction.

---

## 3. Geo-scope hierarchy

**Proposal: replace the single required country string with a `geo_scope` object, country
always resolved as a parent value regardless of the chosen level.**

Current state, cited precisely: `app.py` lines 203-208, inside `api_wizard()` — `market.country`
must resolve to exactly one string; a list of length ≠ 1 is a 400 (`"A study targets exactly one
country/region."`). This is the exact logic being generalized, not replaced wholesale.

New shape, in `config.py`'s config dict (no schema migration needed — this is `config_json`,
see §10):

```python
"market": {
    "geo_scope": {"level": "city", "value": "Bangalore", "country": "India"},
    "country": "India",       # kept as-is: every existing COUNTRY_TABLE lookup (ISO, GDELT
                               # code, demonym, native_names — config.py's COUNTRY_TABLE) is a
                               # country-level fact and doesn't change by state/city.
    "market_terms": [...],    # UNCHANGED MECHANISM — see below
    ...
}
```

`level` is one of `country | state | region | city`. For `country`, `geo_scope.value ==
market.country` (no new information). For `state/region/city`, `country` must still be
resolvable (via `config.resolve_country()`, unchanged) since ISO/GDELT/native-script lookups are
genuinely country-level facts — a Bangalore study still needs India's `.in` ccTLD and Hindi
native-script terms.

**The market-relevance mechanism itself needs zero new code — this is the key reuse.**
`scrapers/news.py`'s `market_signal()` (already fixed to word-boundary matching this session)
takes a flat list of `market_terms` and a `cctld`. Geo-scope just contributes **more terms to the
same list**: `market.market_terms` gains `geo_scope.value` (e.g. "Bangalore") and any obvious
alt-name the geo-scope discovery step surfaces (e.g. "Bengaluru"). No new matching mechanism,
no new function — the exact proven fix from this session's own work directly generalizes.

**This is also what makes hyperlocal discovery "not a separate mechanism," per the brief:**
Layer 1 of §2 receives `geo_scope` alongside category, so a `city`-level study's source-type
suggestion prompt explicitly asks for sources local to *that city*, and §4's discovery step is
seeded with the SAME city value. Hyperlocal is the general mechanism running with `level=city`,
not a special case.

**app.py change required:** replace the single-country validation (lines 203-210) with geo_scope
validation: `level` in the four allowed values; `value` non-empty; `country` resolvable (existing
`resolve_country()`) for every level. This is the "fix that specific logic" the ground rules ask
for — not a rewrite of `api_wizard()`.

**Explicitly not solved by this:** a study still targets exactly ONE geo-scope point. Multi-country-
in-one-run (AUDIT_07 §3's original gap) stays out of scope — this generalizes the *granularity* of
the single point, not its cardinality. Worth saying plainly since the brief frames this as
superseding that gap, and it does, but only in the sense of "the right generalization was
granularity, not multiplicity."

---

## 4. Site/URL discovery within a source type

**This is the section AUDIT_02 §3 most directly constrains, and where I want to be most honest
about what's actually new versus what's being asked of infrastructure that doesn't exist yet.**

AUDIT_02 §3's finding: today's discovery is one hosted-search-API call per configured term (Google
News RSS search, Bing News RSS search, GDELT's API, Reddit's `search.rss`, YouTube's
`search.list`) — **no channel follows outbound links**, and every one of those is a *sanctioned,
public, intended-for-consumption* endpoint. That property is what makes today's approach both
simple and low-risk. An arbitrary lifestyle blog or health directory has no equivalent public
search-feed API — this is the real gap, and it needs a genuinely different mechanism, not a bigger
version of the same one.

**Proposed three-tier approach, cheapest and safest first:**

1. **Seed-site confirmation (reuses `source_discovery.py`/`outlet_discovery.py` unchanged in
   spirit):** Layer 1 of §2 already proposes real, named sites for a source type. Each proposed
   site is validated exactly like `source_discovery.validate()` does today — a reachability probe
   (`source_discovery._probe()`) — before being trusted. This produces a confirmed **seed-site
   list** per project (a new `source_plan` key, e.g. `discovered_sites`, no schema migration).

2. **Sitemap-based content discovery (new, and the mechanism I recommend as primary):** for each
   confirmed seed site, fetch `/sitemap.xml` (and follow one level of sitemap-index nesting, a
   common pattern) via the *existing* `http_client.get_session()` — same retry/rate-limit policy
   every other channel already uses (Ground Rule #2 satisfied directly). Filter the resulting URL
   list by keyword match against the URL path/slug and, where available, `<lastmod>` for date
   bounding. This is genuinely low-risk: sitemaps are an explicit, standard mechanism sites
   publish *for* being crawled — this is the closest thing to "sanctioned" that an arbitrary site
   offers, and it costs nothing beyond the fetch itself.

3. **Official, paid site-scoped search API (optional, explicitly a cost decision, not assumed):**
   where a site has no usable sitemap, or sitemap-slug filtering under-recalls, a real `site:`
   -scoped query via the **Google Programmable Search (Custom Search JSON API)** or **Bing Web
   Search API** — both are official, ToS-compliant, quota-and-billing products. I am **not**
   proposing scraping Google's or Bing's regular web-search results HTML — that is a materially
   different (and materially riskier, ToS-violating) act than consuming Google News' public RSS
   feed, which is what the existing News channel does today. This tier is a real, disclosed
   recurring cost (see §14) and should be treated as an enhancement layered on top of tier 2, not
   a requirement to ship the pilot.

**What this deliberately does NOT do:** crawl a site's own internal links beyond what its sitemap
already lists, or attempt any general-purpose web crawl. Both are higher-risk (arbitrary link-
following can walk into login walls, infinite calendar pages, or content far outside the study's
actual scope) and unnecessary given tiers 2/3 already cover realistic recall for editorial sites.

---

## 4b. Site intelligence — a learning layer, not just a one-shot suggestion

**Added per explicit request: the system should get measurably better at knowing which sites
serve which category/brand over time, not re-derive the same answer from scratch on every
project.** This is a distinct concern from §4's discovery mechanism — §4 is "how do we find
candidate sites for a category," this is "how do we remember which ones turned out to actually be
good, across every project that's ever run, and use that to make the next discovery cheaper and
more confident."

**New table, cited in full in §10: `site_intelligence`, keyed by `(domain, category)` —
deliberately GLOBAL, not scoped to one project's `config_json`.** This is the one piece of this
whole design that must live outside a single project's config, because the entire point is
cross-project reuse: what a Mumbai coffee study learns about `scoopwhoop.com` being a good
lifestyle source for "coffee" should make a *later, unrelated* Bangalore coffee study's discovery
step faster and more confident, not start from zero again.

**The loop, concretely:**

1. **Before** asking the LLM for fresh candidates (§4 tier 1), check `site_intelligence` for
   domains already associated with this category above a confidence threshold. These are proposed
   to the user pre-marked `known: true` with their track record shown (e.g. "used in 4 prior
   studies, 78% of its items passed relevance filtering, never blocked") — genuinely faster and
   more trustworthy than a cold LLM guess, and exactly what "become very smart... over time" means
   in concrete terms.
2. The LLM call **still runs alongside this**, every time — the ledger is a cache/accelerant, not
   a ceiling. New real sites exist and should keep surfacing; over-trusting only what's already
   known would ossify discovery instead of improving it.
3. Anything **not** already in the ledger, or in the ledger with low accumulated confidence
   (few uses, or a poor kept/dropped ratio), is flagged `needs_validation: true` in the review UI —
   **this is the literal "can get manually validated if not sure" mechanism**, implemented as a
   visible flag on the exact same confirm-before-apply checklist §4/§12 already uses, not a
   separate workflow.
4. **After** a real collection run, `site_intelligence` is updated from real outcomes: each
   domain's `times_used`, `items_kept`/`items_dropped` (from the market/relevance gate's actual
   verdict on that run's items), and `times_blocked` (from `source_health`, §7.4) are incremented,
   and `confidence` is recomputed (proposed starting formula:
   `items_kept / max(items_kept + items_dropped, 1)`, discounted toward 0 for sites with very few
   observations so a single lucky/unlucky run doesn't swing the score — exact smoothing is an
   implementation detail, not fixed here). This closes the loop: next time ANY project asks about
   this category, the ledger already reflects what actually happened, not just what an LLM guessed.

**Category-matching is the one real open design question here, named rather than resolved:**
`classify_category()` (§1) returns free text, so the SAME real vertical could be labeled "coffee,"
"coffee / food & beverage," or "food and beverage lifestyle" across different projects — keying
the ledger on exact string equality would fragment history across near-duplicate labels and never
accumulate enough signal on any one of them. Proposed starting behavior: key strictly on exact
string match for the initial build (simple, correct, honest about its own limitation), and treat
"fuzzy/semantic matching across near-duplicate category labels" as a named future enhancement
(§14) rather than building an unproven normalization scheme ahead of real evidence that
fragmentation is actually a practical problem.

**A human validating a site is itself written back to the ledger** (`validated_by_human`,
§10) — once a person confirms a site for a category, future proposals of that exact
(domain, category) pair can be shown as trusted without needing to be validated again, which is
the concrete mechanism by which manual review effort compounds instead of repeating.

---

## 5. Fetching & parsing for arbitrary sites

**Proposal: a generic main-content extractor (new dependency), with the exact same
"never fabricate on failure" contract every existing channel already honors.**

Today's parsers are hand-written per channel (BeautifulSoup for Forums/Quora, `feedparser` for
News, structured JSON for the official APIs — AUDIT_01's file map). An open-ended set of
discovered sites cannot each get a bespoke selector the way `scrapers/forums.py`'s scored-selector
system does for known forum HTML shapes.

Recommend **`trafilatura`** (MIT-licensed, actively maintained, purpose-built for exactly this —
main-content + title/date/author extraction from arbitrary HTML, materially better than a
hand-rolled BeautifulSoup heuristic for unknown page shapes). This is a **new dependency**,
added to `requirements.txt` and **lazy-imported**, matching the existing convention (CLAUDE.md's
own "Conventions" section: "Lazy-import heavy optional deps" — the same pattern already used for
`playwright`, `pytrends`, `anthropic`, `PIL`). If it's not installed, this specific discovery
mechanism is skipped with an honest error, exactly like E-commerce is skipped today when
Playwright isn't installed (`scrapers/ecommerce.py`'s own pattern).

**Failure/fallback path, per "never fabricate":**
1. Fetch via `http_client.get_session()` (Ground Rule #2 — no bypass).
2. Check for a bot-block/CAPTCHA presentation **before** trusting any extracted content — reuse,
   don't reinvent: the exact marker lists already proven live this session,
   `scrapers/ecommerce.py`'s `_BLOCK_MARKERS` (visible-text) and `_CAPTCHA_HTML_MARKERS`
   (raw-HTML, catches the invisible-to-text-extraction case found live on Lazada). A hit here →
   `result.error(...)`, nothing stored.
3. Run `trafilatura.extract()`. If it returns `None` or content shorter than a minimum length
   (mirroring `scrapers/ecommerce.py`'s `_MIN_CONTENT_LEN` pattern) → `result.error(...)`, nothing
   stored.
4. Only a real, non-blocked, non-trivially-short extraction becomes an item.

No case in this path guesses at content when extraction is inconclusive — skip and log, exactly
as the brief requires.

---

## 6. Structured extraction scope

Per the Decided Configuration: **no structured product/catalog extraction** (no price/SKU/listing
scraping from e-commerce-shaped pages). Editorial content that *discusses* products or brands —
a blog post reviewing a coffee shop, a forum thread about a product — stays in scope as ordinary
article content through the §5 pipeline, same as any other page.

**This design does not build any vertical-specific structured schema** (e.g., a doctor-directory
name/credentials/specialty extractor) in this phase — the `structured_data_hint` field from §1's
`classify_category()` output is captured and stored (so it's available later) but nothing acts on
it yet. This is a deliberate scope cut, not an oversight: doing it well requires a per-vertical
schema design exercise that has no evidence behind it yet (no pilot has been run for a
structured-data vertical). Flagged again in §14 as a plausible, explicitly future increment.

---

## 7. Anti-blocking / access infrastructure

**This is the highest-risk section, and I want to state the honest bottom line up front: nothing
proposed here makes blocking go away. What's proposed reduces its frequency, detects it reliably
when it happens (reusing proven code), and makes it visible instead of silent — the same posture
this tool already takes toward Quora/Shopee/Lazada, extended to an open-ended target set.**

AUDIT_03's baseline, restated precisely: **zero proxy rotation, one static User-Agent
(`http_client.py` line 85), and real, repeatedly-observed blocking at modest volume** — Reddit,
GDELT, and Google Trends all degraded specifically because of this session's own repeated
same-IP testing (documented live in HANDOFF.md and reconfirmed in AUDIT_03/05/08). A standing
daily pipeline hitting the *same* discovered sites every day is a strictly harder version of
exactly the pattern that already caused this.

**What's proposed, in order of what's genuinely required versus optional:**

1. **Per-domain rate budgets — extend, don't replace, `http_client.py`.** The `_DomainRateLimiter`
   class (`http_client.py` line 17) is *already* domain-keyed — it just uses one global delay for
   every domain. Proposed change: accept a per-domain override (config-driven — a site flagged as
   "known-sensitive," per wizard step "i," gets a longer delay than a well-behaved blog). This is
   a small, additive change to an existing, already-correct class.

2. **Per-domain concurrency cap, independent of overall worker count.** Whatever the worker-pool
   size in §8, no single domain should ever have more than 1 (default) or 2 concurrent in-flight
   requests — more concurrency to the *same* site is what accelerates blocking, regardless of how
   many *different* sites are being fetched in parallel. Proposed as a semaphore keyed the same
   way `_DomainRateLimiter` already keys its delay state.

3. **`robots.txt` — currently checked nowhere in this codebase.** Proposed: fetch and honor
   `robots.txt` for every discovered site before sitemap/content fetching. This is a real,
   disclosed behavior change (a site that disallows crawling would be excluded, reducing
   discoverable volume for that site to zero) — worth confirming explicitly rather than resolving
   silently either way, since it's a genuine tension between "respect the site's stated wishes"
   and "maximize volume," and the tool's own stated principles lean toward the former.

4. **Per-source health tracking + automatic pause — a genuinely new mechanism, addressing AUDIT_05
   §2's confirmed "no circuit breakers" finding directly.** A new `source_health` table (§10)
   tracks consecutive failures per discovered source. After a small threshold (proposed default:
   3 consecutive failed/blocked fetches), that source is auto-paused for future runs and surfaced
   in the results dashboard's "Access & Reliability" panel (§12) — not retried forever (wasting
   rate budget on something already known to be blocked), and not silently dropped without operator
   visibility (which is exactly the "never fabricate/never hide failure" principle applied to
   infrastructure state, not just item content).

5. **Proxy pool — genuinely required for a standing multi-site daily pipeline at any real scale,
   and a real, disclosed recurring cost, not a code change.** Datacenter proxies are cheaper but
   more commonly pre-blocked by sites already fingerprinting known datacenter IP ranges;
   residential/rotating proxies are far less likely to be blocked but cost meaningfully more per
   request. I am **not fabricating a price** — exact cost depends on request volume and the
   specific vendor, and needs a real quote before committing to it. What I can state plainly: for
   the pilot (§13), I would **not** provision a proxy pool up front — the pilot's real numbers
   (sites blocked, at what volume) are the evidence that should justify this specific spend,
   consistent with the ground rules' instruction not to build access infrastructure speculatively.

6. **When a site blocks regardless of all of the above:** detected via the reused block-marker
   logic (§5), recorded in `source_health`, auto-paused after the threshold, and surfaced to the
   operator — never silently dropped, never retried in a tight loop that burns rate budget, never
   stored as fabricated content. This is the honest, complete answer to "what happens" — not
   "it doesn't happen."

---

## 8. Concurrency / worker model

**Direct answer, as the ground rules require: yes, this design requires the worker-model redesign
AUDIT_06 rated as substantial-redesign-only (bottleneck #1). I am not proposing to avoid that
question.**

Current state, cited precisely: `jobs.py`'s `_worker_loop` (line 48) is a single daemon thread
consuming one shared `Queue`; `_ensure_worker()` (line 36) starts exactly one such thread, once,
ever, for the process's lifetime. Every collection job — regardless of channel, regardless of
project — serializes through that one thread today (AUDIT_01 §3.7, confirmed).

This was already the binding constraint for **10 fixed, well-known-endpoint channels**. This
design adds: (a) an open-ended number of discovered sites, each an independent domain with its
own rate limit that has *no relationship* to any other domain's rate limit, and (b) a standing
daily pipeline that must keep running *alongside* whatever ad-hoc work an operator does
interactively. Keeping a single serial worker here would mean one slow or heavily-rate-limited
domain blocks every other unrelated domain's fetch — strictly worse than today, not merely
unimproved.

**Proposed model:**

- Replace the single worker thread with a **thread pool** (Python's `concurrent.futures.
  ThreadPoolExecutor`, sized N — this work is I/O-bound waiting on network responses, so OS
  threads are an appropriate, low-complexity choice; a full `asyncio` rewrite is not necessary to
  get real concurrency here and would touch far more of the existing synchronous scraper code for
  no additional benefit at this scale).
- The per-domain concurrency cap (§7.2) ensures parallelism happens *across* domains, not within
  one — this is what actually delivers the throughput gain without making blocking worse.
- **The DB write path stays single-writer, deliberately, because SQLite's own concurrency ceiling
  — not just this app's current design choice — genuinely limits concurrent writers to one at a
  time even in WAL mode.** Proposed: worker threads perform fetch + parse concurrently, but hand
  completed items to a single dedicated writer (a queue feeding one thread that calls
  `storage.save_items()`), rather than each worker calling into `storage.py` directly. This keeps
  `storage.py`'s existing single-writer assumption intact (nothing in AUDIT_01's "what should not
  change" list is violated) while still parallelizing the actually-expensive part (network I/O).

**Named risk, not hidden:** AUDIT_05 §2 already flagged concurrent-write behavior against SQLite
as **UNKNOWN, not tested**. The dedicated-writer-thread design above is intended to avoid ever
exercising that untested path at all (only one thread ever calls `storage.save_items()`), but if
write throughput itself becomes the bottleneck at real daily-pipeline scale, the honest next step
named here — not built now — is evaluating a move off SQLite to a real client-server database
(e.g. Postgres). This is a genuine "if the pilot's numbers say so" decision, not assumed necessary
today.

---

## 9. Job resumability & scheduling

Per Ground Rule #5, this is required for this build, not deferred. Current state: `jobs.py`'s
`_jobs` dict is process-memory only (confirmed lost on every restart this session — AUDIT_01/05);
the persisted `runs` table (`migrations.py` `_m001_initial`) records a run's *final* outcome but
has no notion of partial progress within a still-running job.

**Proposed: checkpoint each discovered unit of work as it completes, not just the job as a
whole.** A "collect from N discovered sources" job is broken into one unit per source (a
site/feed/URL). Each unit's completion is committed to a new `runs.checkpoint_json` column
(§10) **immediately**, not held in worker memory — so a crash mid-job leaves a durable record of
exactly which units are done. On restart, a resumed run reads the checkpoint and skips
already-completed units entirely, rather than re-fetching (wasting rate budget, not just time) or
silently restarting from zero.

**Two distinct job kinds, tracked explicitly** (`runs.job_kind`, §10): `backfill` (the one-time,
large, 2-year historical job — chunked and checkpointed per the above) and `daily` (the standing
incremental job, "since last successful run," lightweight by construction). These are genuinely
different operational concerns — a `daily` run failing should probably alert/retry soon; a
`backfill` run failing mid-way should resume from checkpoint, not restart from day one.

**Scheduling reuses `scheduler.py` unchanged in mechanism** — it already does exactly "poll a
`schedules` table, enqueue via `jobs.enqueue()` when due" (AUDIT_01's file map). The `daily` job
kind is just a new schedule row per project; the one-time `backfill` is triggered explicitly (like
today's "Extensive research" button), never scheduled.

---

## 10. Data model changes

Following `migrations.py`'s existing append-only pattern (`_m001_initial`, `_m002_story_clusters`
— never edit either, only append). Proposed `_m003_category_discovery`:

**No migration needed at all for most of this** — `projects.config_json` is already a free-form
JSON blob (`migrations.py` line 22); `geo_scope`, `category`, the discovered source-type list, and
language-confirmation state are all just new keys within it, exactly like `market_terms`/
`source_plan` already are. This mirrors how `term_expansion.py`/`outlet_discovery.py` needed zero
schema changes.

**What genuinely needs new columns/tables** (per-item and per-run facts, not per-project config):

```sql
-- items: raw retention (Ground Rule #4) + per-item tagging for dashboard breakdowns
ALTER TABLE items ADD COLUMN raw_html TEXT;        -- nullable; the fetched page, for future
                                                     -- re-processing without re-fetching
ALTER TABLE items ADD COLUMN category TEXT;
ALTER TABLE items ADD COLUMN source_type TEXT;

-- runs: job-kind distinction + resumability checkpoint
ALTER TABLE runs ADD COLUMN job_kind TEXT;          -- 'backfill' | 'daily' | NULL (existing runs)
ALTER TABLE runs ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}';

-- new table: per-source circuit-breaker state (§7.4)
CREATE TABLE IF NOT EXISTS source_health (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id         INTEGER NOT NULL REFERENCES projects(id),
    source_url         TEXT NOT NULL,
    domain             TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_status        TEXT,               -- 'ok' | 'blocked' | 'error'
    last_checked_at    TEXT,
    paused             INTEGER NOT NULL DEFAULT 0,
    UNIQUE(project_id, source_url)
);
CREATE INDEX IF NOT EXISTS idx_source_health_project ON source_health(project_id);

-- new table: cross-project site intelligence ledger (§4b) — deliberately GLOBAL,
-- no project_id, since the whole point is reuse across every project that ever runs.
CREATE TABLE IF NOT EXISTS site_intelligence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    domain              TEXT NOT NULL,
    category            TEXT NOT NULL,      -- exact-string keyed for now — see §4b's named
                                              -- open question on category-label fragmentation
    name                TEXT,
    source_type         TEXT,
    times_suggested     INTEGER NOT NULL DEFAULT 0,
    times_used          INTEGER NOT NULL DEFAULT 0,
    items_kept          INTEGER NOT NULL DEFAULT 0,
    items_dropped       INTEGER NOT NULL DEFAULT 0,
    times_blocked       INTEGER NOT NULL DEFAULT 0,
    validated_by_human  INTEGER NOT NULL DEFAULT 0,
    confidence          REAL,               -- recomputed after each run, see §4b's formula
    last_used_at        TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE(domain, category)
);
CREATE INDEX IF NOT EXISTS idx_site_intel_category ON site_intelligence(category);
```

`raw_html` retention directly closes AUDIT_06 §1's "no raw-source retention" finding — but only
for content collected through this NEW pipeline; retrofitting it onto the 10 existing channels is
explicitly out of scope here (a separate, larger decision about existing data volume/cost, not
assumed free). Size is a real, if currently small, concern — `data/marketlens.db` is 2.2MB today
(AUDIT_00 §1) with no raw retention at all; I'm not proposing a size cap or external file storage
preemptively, since there's no evidence yet this becomes a real problem — revisit if the pilot's
real numbers say otherwise.

---

## 11. Default behavior

**Confirmed, directly: category classification (§1), source-type mapping (§2), and geo-scope-
driven discovery (§3/§4) all run automatically as part of normal collection for this new
pipeline — no separate manual trigger, satisfying Ground Rule #1 and AUDIT_07's core finding.**
This is a deliberate difference from the existing `term_expansion.py`/`outlet_discovery.py`
features, which remain manual-trigger (they are not being changed by this design) — the new
pipeline is being built default-on from day one, as instructed.

**One explicit, deliberate exception, named per the instruction not to default to manual by
omission: language selection.** Per the Decided Configuration, languages are AI-suggested (same
generative approach as everything else here) but require human confirmation before the run
proceeds. Reason: each added language roughly multiplies the discovery/fetch surface — this
session's own empirical work proved it directly (the 87-feed expansion, AUDIT_08) — so language
choice has a real, direct cost and scope consequence that the other automatic steps don't carry
in the same way. This is the one wizard step (§12, step "c") that blocks on a human click before
anything downstream runs.

**A second, softer gate proposed (open to being removed if considered redundant):** the
"known-sensitive-source heads-up" (wizard step "i") is informational with an
acknowledge-and-continue action, not a decision the user makes per source — it doesn't block
automatic operation, it just makes sure blocking risk isn't a silent surprise.

---

## 12. Frontend / wizard design

**Reuse confirmed, per the ground rules: `app.py`'s FastAPI routes stay the API layer.** Existing
endpoints (`/api/reference/languages`, `/api/reference/countries`, the wizard endpoint, the
suggest/apply pattern from `term_expansion`/`outlet_discovery`) are extended with new routes for
category classification, geo-scope-aware source-type suggestion, language suggestion, and the new
resumable-job/dashboard data — not replaced. The single-country wizard validation (`app.py` lines
203-210) is fixed in place, per §3, not rewritten wholesale.

**What changes is the presentation layer — `static/index.html`/`static/app.js`.** This is a real,
disclosed trade-off, stated rather than assumed:

| | Keep vanilla JS, no build step | Introduce a modern frontend (React + Vite, or similar) |
|---|---|---|
| Consistent with | The existing, deliberate "no build step" simplicity (README/CLAUDE.md's stated design) | — |
| Cost | Hand-rolled DOM code for a longer step-wizard and dashboards gets verbose fast — `static/app.js` is already 1100+ lines for a *simpler* flow (AUDIT_01 §2) | A genuine new toolchain dependency (npm, a build step) this project has never had |
| Benefit | Zero new tooling, zero deploy complexity | Real component/state infrastructure for a materially longer multi-step flow, easier charting for the dashboards this brief explicitly asks for, more plausible path to "professional-looking, not templated-default" |

**Recommendation: the modern-frontend option**, given the brief explicitly asks for a polished,
step-based, dashboard-bearing UI — but this is exactly the kind of decision the ground rules say
must be surfaced, not silently chosen, so treat this as a specific approval point distinct from
approving the rest of this document.

**Step flow** (mapped to the reference list a–j; each step is a client-side wizard state, not a
persisted project, until the final step — avoiding half-created projects for abandoned wizard
sessions):

| Step | Always shown? | Backend call |
|---|---|---|
| a. Term + category | Always; confirmation sub-step only if `confidence` is low (§1) | `classify_category()` (new) |
| b. Geo-scope | Always | `config.list_countries()` (existing) for country level; free text for state/region/city |
| c. Languages | Always; **blocks on explicit confirmation** (§11) | new `suggest_languages(category, geo_scope)` |
| d. Source types | Always | §2 Layer 1 (new) |
| e. Brands/competitors | Always | **Reuses `term_expansion.py`'s existing brand-suggestion output** unchanged |
| f. Relevance criteria | Always | New config flag `market.relevance_mode: "narrow"\|"broad"` (Decided Config) |
| g. Date range / run mode | Always | New: backfill window (default 2 years) + daily-continue toggle |
| h. Volume cap | Always | Per-source numeric field; proposed default below |
| i. Sensitive-source heads-up | Only if any confirmed source is flagged (§7.3/§11) | Informational, reuses AUDIT_03's known cases as seed knowledge (Quora/Shopee/Lazada-class patterns) plus anything `source_health` already knows about |
| j. Review & launch | Always | Extended `POST /api/projects/wizard` (creates project) + triggers `backfill` job + creates `daily` schedule if toggled |

**Proposed default volume cap: 500 items per source for the initial backfill**, configurable per
study. This is a starting point, not a derived fact — flagged in §14 as needing real-world
validation against the pilot.

**Results dashboard (new):** summary tiles (by category, source-type, language, geo — extending
`analytics.py`'s existing aggregation pattern, e.g. new `items_by_source_type()`/`items_by_geo()`
alongside its existing `sentiment_by_channel()`), a sample-items feed, and an **Access &
Reliability panel** driven directly by the new `source_health` table — this is the observability
AUDIT_06 flagged as absent, folded into this UI work rather than built separately later, exactly
as instructed.

**Daily-pipeline status view:** a run-history timeline filtered to `runs.job_kind = 'daily'`,
items-per-day, and the same `source_health` error/blocked visibility — no exotic new backend
needed, this is a view over data the resumability work (§9/§10) already produces.

---

## 13. Phased rollout proposal

| # | Increment | Depends on | Frontend/backend |
|---|---|---|---|
| 1 | Category classification + geo-scope validation + source-type mapping **+ site-intelligence ledger lookup/scoring (§4b)** — all decision logic, no fetch infra; the ledger's *update* step naturally waits for #4's real run data | Nothing new | Backend |
| 2 | Migration `_m003` (§10) | Nothing new | Backend, mechanical |
| 3 | Generic fetch/parse pipeline (`trafilatura` + reused block detection), tested against recorded/mocked real pages first, matching the existing "network mocked in tests" convention | #2 (needs `raw_html` column) | Backend |
| 4 | **Pilot: coffee / India / lifestyle-blogs source type only** — wires §1-§4 together live, real numbers reported (sites discovered, validated reachable, pages found via sitemap, pages successfully extracted) exactly like AUDIT_08's methodology | #1, #2, #3 | Backend |
| 5 | Anti-blocking infra (§7) — **only what the pilot's real results show is needed**; do not provision a proxy pool speculatively | #4's real results | Backend |
| 6 | Worker pool + resumability (§8/§9) — the biggest, riskiest backend increment; sequence after the pilot proves the mechanism works at all on a single source type, before generalizing to daily-recurring, multi-source-type load | #4 | Backend |
| 7 | Frontend wizard steps a–e | #1 only (does NOT need #3/#4/#5/#6) | Frontend, **can start in parallel with #3-6** |
| 8 | Frontend wizard steps f–j + results dashboard + daily-pipeline status view — built against the pilot's *actual* data, not a mockup reconciled later | #4 (needs real run data to design against) | Frontend, sequenced after pilot |
| 9 | Generalize beyond the pilot: additional source types (News/Reddit/Forums route through Layer 2's `existing_channel` strategy unchanged; only genuinely new source types exercise the new generic pipeline) and additional categories, each reported with real numbers before the next | #4-8 | Both |

**Why coffee/India/lifestyle-blogs as the pilot:** it's the one vertical this session has already
built real, live-tested infrastructure and real data around (`term_expansion`, `outlet_discovery`,
the `market_signal` fixes are all already validated against exactly this project) — and lifestyle
blogs are the specific source type this session's own real example (the ScoopWhoop coffee
articles) demonstrated is currently under-served. Narrowing to one source type (not "all of
News/lifestyle/health/hyperlocal at once") keeps the first real numbers legible.

---

## 14. Open questions and trade-offs (unresolved — surfacing them, not hiding them)

1. **Paid search-API subscription** (§4, tier 3) — a real cost decision for site-scoped discovery
   beyond sitemap-based recall. Not resolved here; needs a business decision once the pilot shows
   whether sitemap-only recall is actually insufficient.
2. **Residential/rotating proxy service** (§7.5) — real, recurring cost for the standing daily
   pipeline at any real scale. No price is fabricated here; needs a vendor quote, and I've
   proposed not provisioning it until the pilot's real block rate justifies it.
3. **Frontend stack** (§12) — vanilla JS vs. a new build-step frontend. Recommended the latter,
   but flagged as its own explicit approval point, not bundled into "approve this whole document."
4. **SQLite write concurrency under a real worker pool** (§8) — AUDIT_05 already listed this as
   untested; the dedicated-single-writer-thread design is meant to avoid ever needing an answer,
   but if daily-pipeline write volume across many sources proves too much even for that, the named
   next step is evaluating Postgres — not decided or built now.
5. **`robots.txt` honoring** (§7.3) — a real tension between respecting a site's stated crawl
   preferences and maximizing discoverable volume. Proposed to honor it; flagging that this is a
   values-driven choice, not a purely technical one, and worth explicit sign-off.
6. **Vertical-specific structured extraction** (§6) — explicitly deferred, not solved, in this
   phase. The `structured_data_hint` field is captured for future use but nothing consumes it yet.
7. **Exact per-source volume cap default** (500/source proposed, §12) — a starting point for
   discussion, not a derived technical fact; likely needs adjustment once the pilot's real
   per-source yield is known.
8. **Known-sensitive-source handling** (§7.3/§11) — proposed as informational
   acknowledge-and-continue. Could reasonably be made a stricter per-source opt-in gate instead;
   open to either.
9. **Retrofitting raw-content retention to the 10 existing channels** — explicitly out of scope
   here (§10); this design only guarantees retention for content collected through the new
   pipeline going forward.
10. **Category-label fragmentation in the site intelligence ledger** (§4b) — free-text category
    labels mean the same real vertical can accumulate history under several near-duplicate
    strings instead of one. Proposed to start with exact-string keying and treat semantic/fuzzy
    matching as a future enhancement once real usage shows whether this actually fragments
    meaningfully, rather than building an unproven normalization scheme ahead of evidence.

**This is not a finished, risk-free plan.** The riskiest single item is §8/§9 together (the
worker-pool + resumability redesign) — it's the one increment that's both structurally necessary
(the daily-pipeline requirement genuinely can't be met without it) and the one with the least
precedent in this codebase to build on. The rollout order in §13 is deliberately structured to
prove sections 1-5 work at all, live, on one narrow slice, before spending that effort.

**Waiting for explicit approval — on this document as a whole, and specifically on the frontend
stack choice (§12) and the anti-blocking spend decisions (§7/§14 items 1-2) — before any Phase B
implementation begins.**
