# AUDIT_04 — Data Model, Deduplication, AI/LLM Architecture

Reads AUDIT_00–03 as prior context.

---

## Section 1 — Data model

**Tables** (all in one SQLite file, `data/marketlens.db`, schema defined entirely in
`migrations.py`'s `_m001_initial` + `_m002_story_clusters`):

| Table | Primary key | Foreign keys | Notable columns |
|---|---|---|---|
| `projects` | `id` | — | `config_json` (the ENTIRE project config — market, keywords, source plan — as one serialized JSON blob, not normalized into columns) |
| `runs` | `id` | `project_id → projects(id)` | `channel`, `params_json`, `status`, `rows_returned`/`rows_new`/`rows_duplicate`, `errors_json` |
| `items` | `id` | `project_id → projects(id)`, `run_id → runs(id)` | `source` (the **channel** name, not the outlet — see Section 2), `content_hash`, `title`, `text`, `link`, `published`, `extra_json`, `cluster_id` (added by `_m002`) |
| `analysis` | `id` | `item_id → items(id)` (UNIQUE — at most one analysis row per item, ever), `project_id → projects(id)` | `sentiment`, `sentiment_score`, `language`, `summary_en`, `purchase_driver`, `trend_category`, `brand_focus`, `raw_json` (the full unparsed Claude tag object) |
| `market_intel` | `id` | `project_id → projects(id)` | `entry_type` ('cited' vs manual-ad), `source_name`/`source_url`/`publication_date`/`accessed_date`/`confidence` — every cited fact carries its own citation columns |
| `schedules` | `id` | `project_id → projects(id)` | `channel`, `interval_seconds`, `next_run`, `paused` |
| `users` | `id` | — | `password_hash`, `salt`, `is_admin` — team-mode auth only |
| `audit_log` | `id` | `project_id` (nullable, no FK enforcement keyword used) | `action`, `detail`, `acting_user` |

**Indexes** (from `migrations.py`): `idx_items_project`, `idx_items_run`, `idx_items_source`
(composite `project_id, source`), `idx_analysis_project`, `idx_intel_project`,
`idx_items_cluster` (composite `project_id, cluster_id`, added by `_m002`),
`idx_items_published` (composite `project_id, published`, added by `_m002`).

**Where specific data lives, explicitly:**
- **Raw vs. processed data — explicitly determined: only ONE tier is stored, not two.**
  `items.text` is whatever each scraper decided to extract at insert time (e.g. News's title-echo
  RSS summary, or a resolved article's first paragraphs, per `scrapers/news.py`'s own logic) — this
  IS the stored "content," and no earlier/rawer version (e.g. the full raw HTML page, the raw RSS
  XML) is retained anywhere in the schema or on disk after a successful `save_items()` call.
  Confirmed: `items` has no `raw_html`/`raw_response` column, and no file-based raw-content store
  exists (`data/` only holds the SQLite file, `.mlz` archives, and generated exports, per AUDIT_00
  §1). **If extraction logic changes later, historical items cannot be re-processed from a
  preserved raw source — they would need to be re-collected.**
- **Metadata:** `source` (channel), `published`, `link`, and channel-specific extras live in
  `extra_json` (a free-form JSON blob per item — e.g. E-commerce stores `price`/`image_urls` here,
  News stores `engine`/`is_google_news`/`relevance_precheck` here, per prior session's own commits
  referencing these exact keys).
- **Language:** captured only at analysis time, as a column on the `analysis` table
  (`analysis.language`, an LLM-inferred ISO code) — **not** stored on the `items` row itself at
  collection time. An unanalyzed item has no queryable language field.
- **Geography:** not a per-item column at all — the project's single configured
  `market.country`/`market.market_terms` (project-level, not item-level) is the only geography
  concept in the schema; there is no per-item geo-tag (e.g., which specific city/region an item's
  content concerns).
- **Author / engagement metrics:** **not modeled as first-class columns anywhere.** Whatever an
  individual scraper captured (e.g. a Reddit post's author, if present) would have to live inside
  `extra_json`, since `items` has no `author`/`likes`/`upvotes`/`shares`/`comment_count` column.
  This audit did not find confirmed evidence that any scraper actually writes engagement metrics
  into `extra_json` either — a targeted read of each `collect()` function's `result.add({...})`
  call would be needed to state definitively per-channel (flagged for a future check, not
  re-derived here to avoid duplicating AUDIT_03's already-completed per-source table).
- **Canonical URLs:** **not modeled** — `items.link` stores whatever URL string the scraper
  returned, with no separate canonical-URL field or canonicalization step (see Section 2, dedup,
  for the direct consequence of this).
- **Embeddings / vector representations:** **absent entirely.** No embedding column, no vector
  index, no vector-store integration anywhere in the schema or codebase (confirmed: no `pgvector`,
  `faiss`, `chromadb`, or similar dependency in `requirements.txt`, and no embedding-generation
  code found in `analysis.py` or elsewhere).
- **AI classifications:** the `analysis` table's columns directly (`sentiment`, `brand_focus`,
  `purchase_driver`, `trend_category`, `emotion`, etc.) plus the full raw model output preserved
  verbatim in `raw_json` — so even fields not promoted to their own column are recoverable.

---

## Section 2 — Deduplication

**The actual algorithm** (`storage.py`, cited precisely):
- `compute_content_hash(source, link, title, text)` (line 93) builds
  `sha256("{source}|{link}|{title}|{text[:200]}")`, where `source` = the **channel name**
  (`news`, `reddit`, etc. — confirmed by its caller, `jobs.run_collection`, passing `channel` as
  the `source` argument to `storage.save_items`), `link`/`title` are only `.strip()`-normalized
  (no case-folding, no whitespace-collapsing beyond the outer strip), and only the **first 200
  characters** of `text` participate in the hash (`text[:200]`).
- Uniqueness is enforced by a `UNIQUE(project_id, content_hash)` constraint at the DB level
  (`migrations.py` line 54) — `save_items()` (storage.py line 289) also does a pre-check `SELECT`
  before inserting, with an `except sqlite3.IntegrityError` fallback (line 339) if a concurrent
  insert raced past that check, so the constraint is the actual source of truth, not the
  pre-check alone.
- **Separately**, `_find_cluster_match()` (line 252) does *fuzzy* near-duplicate grouping via
  `difflib.SequenceMatcher(None, norm_title_a, norm_title_b).ratio() >= 0.82`
  (`_CLUSTER_SIMILARITY_THRESHOLD`, line 229), scoped to items with a parseable `published` date
  within a **±2-day window** (`_CLUSTER_WINDOW_DAYS`, line 228) of each other, in the same
  project. Title normalization (`_normalize_title_for_clustering`, line 236) strips a trailing
  " - Outlet Name"-style suffix, lowercases, and strips punctuation before comparing. This
  clustering is **deliberately not deletion/merging** — it assigns a shared `cluster_id` so
  `storage.count_unique_stories()`/`cluster_sizes()` can report a syndication-adjusted count
  alongside the raw item count; every row is kept.

**Explicitly testing the algorithm against each named scenario, with code citations:**

| Scenario | Caught by exact `content_hash` dedup? | Caught by fuzzy `cluster_id` grouping? | Why (citation) |
|---|---|---|---|
| Exact duplicate URL (re-scraped, byte-identical title/text) | **Yes** | N/A (would be same row) | Identical `source\|link\|title\|text[:200]` string → identical SHA-256 → `UNIQUE` constraint rejects the second insert (`storage.py` lines 93-109, 309-314) |
| Same URL with a tracking parameter appended (e.g. `?utm_source=x`) | **No** | Only if published dates are within 2 days AND titles are ≥0.82 similar | `link` is used **raw**, with no query-string stripping/canonicalization anywhere in `compute_content_hash` or its caller — a different query string produces a different hash unconditionally |
| Syndicated articles across outlets (same wire story, different `link`, near-identical title) | **No** (by design — each outlet's copy is a legitimate distinct item with its own lineage) | **Yes, if titles clear the 0.82 similarity bar and dates are within ±2 days** | This is the exact case `_find_cluster_match`'s own module comment (`storage.py` lines 221-227) says it exists to handle |
| Near-identical (not byte-identical) articles, non-syndicated | **No** | **Conditionally** — depends entirely on the 0.82 `SequenceMatcher` ratio and the 2-day date window; a title with a materially different headline about the same event, or an item with no parseable `published` value, is **never** clustered (line 260-261: `if pub is None: return None`) |
| Updated articles (same URL, content edited after first collection) | **No**, if the edit changed anything within the first 200 chars of `text` (or the title) — produces a new hash, inserted as a **second, separate row** for what is conceptually the same article | Possibly, if titles still match closely enough within the date window | There is no update/versioning/supersession mechanism in the schema — an "update" is architecturally indistinguishable from "a new, related item" |
| Same Reddit post found via multiple queries (e.g. appears in both `new.rss` and `search.rss` for one subreddit) | **Yes** | N/A | Same `link`/`title`/`text` → same hash → correctly deduplicated within the same run or across runs |
| Same content in multiple languages (e.g. an English and a Hindi article about the same event) | **No** (correctly — these are genuinely different content, not duplicates) | **No** — `_normalize_title_for_clustering` does not translate or cross-reference scripts; a Devanagari-script title will never match a Latin-script title's `SequenceMatcher` ratio | Neither mechanism has any cross-language awareness; this is expected behavior, not a gap, for two genuinely distinct pieces of content |
| Quoted/reposted content (e.g. a forum post or Reddit comment quoting a news article) | **No** — different `source` (channel), different `link`, different surrounding text | **No** — clustering only compares `items.title`, and a comment/forum post frequently has no distinct "title" in the same sense (channel-dependent; not verified per-channel in this phase) | Different channel + different `link`/`title` structure means neither mechanism was designed to, or does, catch this case |

**Performance note relevant to correctness at scale (flagged for Phase 5, cited here since it's
literally in the dedup code path):** `_find_cluster_match()` runs a `SELECT ... WHERE project_id=?
AND published BETWEEN ? AND ?` and then does an **O(candidates) `difflib.SequenceMatcher` string
comparison against every row in that date window, for every newly-inserted item** (lines 265-277).
For a project with heavy same-day volume, this is a per-insert cost that grows with how many items
already exist in that ±2-day window — not indexed or short-circuited beyond the date-range
`WHERE` clause (`idx_items_published` narrows the SQL query, but the `SequenceMatcher` loop itself
is still linear in Python over however many rows that query returns).

---

## Section 3 — AI / LLM architecture

**Every AI/LLM call site in the repository**, model/purpose/input/output/prompt-location/
frequency, cited precisely:

| Call site | Model / provider | Purpose | Input | Output | Prompt location | Invocation frequency | Caching | Retry / fallback |
|---|---|---|---|---|---|---|---|---|
| `analysis.analyze_batch()` → `analysis.call_claude()` (`analysis.py` line 130, wrapping `_default_call` line 116) | `anthropic` SDK, model = `settings.analysis_model` (env `ANALYSIS_MODEL`, default `claude-haiku-4-5` per `.env.example`) | Batch-tag collected items: sentiment, summary, purchase driver, brand focus, trend category, emotion, promo flag | Up to `BATCH_SIZE=12` (line 19) unanalyzed items' title+text, joined into one prompt (`build_prompt`, line 33) | A JSON array of one tag-object per item, parsed by `parse_response` (line 71) | `analysis.py` `build_prompt()`, lines 33-68 | **Once per 12 items** — NOT once per query and NOT once per single item; `analyze_all()` (line 168) loops calling `analyze_batch()` up to `max_batches=1000` times per invocation, so total calls for a project = `ceil(unanalyzed_count / 12)` | **No caching** — an item is tagged at most once ever (enforced by `analysis.item_id UNIQUE`, so `save_analysis` is naturally idempotent), but there is no response cache preventing a re-send of the same prompt content if, e.g., analysis were re-run on identical items in a different project | On exception, the **whole batch** is abandoned with nothing written (`analysis.py` lines 154-157) — items stay unanalyzed and are retried on the next "Analyze" click; no automatic retry within a single call |
| `source_discovery.suggest_sources()` (`source_discovery.py`) | Same `anthropic` SDK via `analysis.call_claude`, `max_tokens=2000` | Propose candidate news/e-commerce/forum/subreddit sources for the project's market+category | One prompt built from project config (market, category, brand, competitors) | A JSON object of candidate lists, each then independently network-validated (feed-health check / reachability probe) before being returned | `source_discovery.build_prompt()` | **Once per user click** of "✨ Suggest sources" — a project-level action, not tied to item count or query volume at all | No caching — a fresh suggestion set is generated every click | On exception, `app.py`'s `api_suggest_sources` catches it and returns an HTTP 400 with the error message (no automatic retry) |
| `term_expansion.suggest_terms()` (`term_expansion.py` line 103) | Same `anthropic` SDK via `analysis.call_claude`, `max_tokens=1500` | Expand one term into variants/brands/translations | One prompt built from project config + the one term string | A JSON object with `variants`/`brands`/`translations` lists, parsed by `parse_expansion` (line 78) | `term_expansion.build_prompt()`, lines 35-76 | **Once per user click** of "✨ Expand a term" — a project-level, per-term action, independent of item/query count | No caching | Same pattern — `app.py`'s `api_suggest_terms` catches and returns HTTP 400 on exception |
| `scrapers/image_analysis.py` `_vision_read()` (line 49) | `anthropic` SDK, vision-capable model = `settings.vision_model` (env `VISION_MODEL`, default `claude-haiku-4-5`), `max_tokens=500` | Describe/classify one product image (packaging, labels, claims, prices) | One image's raw bytes + media type | A free-text description, stored as the new item's `text` | `scrapers/image_analysis.py`, inline in `_vision_read` | **Once PER IMAGE** — this is the one call site in the whole codebase with a **per-document**, not per-query/per-batch, invocation pattern; cost scales linearly with the number of images collected by the E-commerce channel | No caching — re-running image analysis on the same image set would re-call the model for every image again (no hash-based skip-if-already-analyzed check was found in this file during this phase — UNKNOWN whether one exists elsewhere; not confirmed either way) | UNKNOWN — this file's exception handling around the `anthropic` call was not traced in this phase (flagged as an open question) |

**Answering the specific "is AI used for X" checklist:**

| Capability | Implemented? | Evidence |
|---|---|---|
| Query expansion | **Yes, but only opt-in** | `term_expansion.py` — see AUDIT_02 Section 2 for the full distinction between this and the always-on, purely-mechanical `derive_relevance_terms` |
| Translation | **Yes, as part of term expansion only** | Same call site — `translations` field of `term_expansion.suggest_terms()`'s output; there is no standalone "translate this item's text" feature anywhere else |
| Summarization | **Yes** | `analysis.py`'s per-item `summary_en` tag (an English one-line summary, per `build_prompt`'s field list) |
| Classification (sentiment) | **Yes** | `analysis.py`'s `sentiment`/`sentiment_score` tags |
| Topic extraction | **Partially — as a fixed-vocabulary tag, not open-ended extraction** | `analysis.py`'s `trend_category` tag is constrained to a project-configured taxonomy (`_trend_categories`, line 28) plus an "other/emergent" catch-all — this is classification into pre-defined buckets, not open-ended topic/keyword extraction |
| Entity extraction | **No dedicated entity-extraction step found** | `brand_focus` (target brand / named competitor / category-generic / corporate / unrelated) is the closest analog, but it is a fixed 5-way classification, not general named-entity extraction (people, orgs, locations) |
| Relevance scoring | **Yes, but split across two DIFFERENT mechanisms that must not be conflated** — (1) a **non-AI**, deterministic term-presence check (`scrapers/relevance.py`'s `contains_any_term`/`term_appears_anywhere`) gates whether a scraped page is stored at all; (2) the LLM-assigned `brand_focus` tag (analysis-time, AI-driven) is used **afterward** as a semantic backstop/refinement signal (per AUDIT_01's citation of the "semantic relevance backstop" design) | `scrapers/relevance.py`, `analysis.py` |
| Deduplication | **No** | Confirmed in Section 2 — dedup is 100% deterministic (SHA-256 hash + `difflib.SequenceMatcher`), zero LLM involvement |
| Clustering | **No** | Same — `difflib`-based, not embedding/LLM-based |
| Semantic search | **No** | No embeddings exist (Section 1); `items-table` filtering (`app.py api_items_table`) is a plain Python substring `.lower() in hay` check across title/text/summary — confirmed by reading that function in AUDIT_01's file map, re-confirmed here: this is literal substring matching, not semantic similarity |

---

## Open questions for Phase 5

1. `scrapers/image_analysis.py`'s exception/retry handling around its per-image Claude call —
   not traced in this phase; directly relevant to Phase 5's cost-model question (a large
   E-commerce image set could mean many sequential per-image LLM calls with unknown resilience to
   a mid-run failure).
2. `analysis.analyze_all()` runs **synchronously inside the HTTP request handler** (`app.py`'s
   `api_analyze`, calling `analysis.analyze_all` directly — NOT via `jobs.enqueue`), unlike every
   collection channel. For a project with hundreds of unanalyzed items, this could hold one HTTP
   request open for the full duration of dozens of sequential Claude calls with zero incremental
   progress feedback to the client beyond a single final JSON response. This is a genuine
   Phase-5-relevant reliability/UX question: what happens if that request is interrupted
   mid-batch-loop (client disconnects, reverse proxy times out, server restarts)?
3. `_find_cluster_match()`'s per-insert linear scan (Section 2) — at what item-count-per-2-day-
   window does this become a measurable slowdown? Needs either a load test or an explicit
   Big-O statement in Phase 5, not guessed.
4. Whether any scraper actually populates engagement metrics (likes/upvotes/comment counts) into
   `extra_json` — flagged as not-yet-confirmed per-channel in Section 1; would need a full read of
   each channel's `result.add({...})` call, deferred as it's peripheral to Phase 4's core scope.
5. `jobs.py`'s in-memory job-status dict (confirmed in AUDIT_01) vs. the DB-persisted `runs` table
   — Phase 5 should state precisely what a user loses (job polling continuity) vs. keeps (the
   actual collected data and run history) across a process restart mid-job.
