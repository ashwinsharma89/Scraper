# AUDIT_02 — Execution Flow, Query Expansion, Discovery vs. Crawling

Reads `AUDIT_00_inventory.md` and `AUDIT_01_architecture.md` as prior context.

---

## Section 1 — End-to-end execution flow: user searches "coffee"

Tracing the literal path a category term "coffee" takes, cite-by-cite. Two distinct entry points
exist for a term to enter the system — they are traced separately because they behave differently.

### 1a. Entry point A — the intake wizard (`product.category = "coffee"`)

1. **Entry:** `POST /api/projects/wizard` with `{"product": {"category": "coffee", ...}}` →
   `app.py` `api_wizard()` (line 187).
2. **Validation:** only checks that brand OR category is non-empty (`app.py` lines 192-195) and
   that `market.country` resolves to exactly one string (lines 196-210). **No validation or
   normalization of the term itself** (no spell-check, no case-folding beyond what Python does
   implicitly, no length/profanity/language check).
3. **No expansion at this stage.** `config.run_wizard()` calls `suggest_keyword_structures(brand,
   competitors, category, languages)` (`config.py` line 428) which places the literal string
   `"coffee"` into exactly one slot — `category_generic` — for the **primary language only**
   (`config.py` lines 439-447: `if i == 0: ... if category: slots["category_generic"] =
   [category]`). Every other configured language's `category_generic` slot is left as `[]` (empty
   list) — confirmed by the same loop body: the `if i == 0` guard means only index 0 (the first
   language in the study's `languages` list) is ever seeded.
4. **Relevance terms:** `config.derive_relevance_terms(brand, competitors, category)` (`config.py`
   line 453) does **pure string tokenization** — `category.replace("/", " ").replace(",", "
   ").split()`, keeping tokens longer than 2 characters (line 459). For `category="coffee"` this
   produces `["coffee"]`; for `category="instant noodles"` it would produce
   `["instant","noodles"]` as two SEPARATE relevance terms. This is deterministic string-splitting,
   **not** semantic/synonym expansion — "coffee" never becomes "espresso" or "kaapi" here.
5. **Feed URLs generated:** `build_google_news_feeds`/`build_bing_news_feeds` (`config.py`) iterate
   `keywords.by_language` and emit exactly **one feed per (language, structure) key that has a
   non-empty term list** — so for a category-only "coffee" study in English only, this produces
   exactly 1 Google News feed and 1 Bing News feed (both querying the literal string `coffee`).
6. **What every OTHER search-driven channel queries:** confirmed by direct citation —
   `scrapers/reddit.py` line 171 (`terms = relevance_terms(cfg)`), `scrapers/youtube.py` line 41
   (same), `scrapers/ecommerce.py` line 170 (`keywords = params.get("keywords") or
   sp.get("ecommerce_keywords") or relevance_terms(cfg)`), `scrapers/trends.py` line 56 (a
   configured keyword list, capped to 5 by pytrends' own request limit). **Every one of these
   channels queries the exact literal term(s) from step 4 above and nothing else**, unless the
   user has separately added more terms (see Entry point B).

### 1b. Entry point B — AI term expansion (`term_expansion.py`, opt-in, post-wizard)

This is a **completely separate, manually-triggered action** — it is never invoked automatically
by the wizard, by a collection job, or by any scheduled task.

1. **Trigger:** user clicks "✨ Expand a term" in the Source Plan tab (`static/app.js`, the
   `expand-term-btn` handler calling `expandTerm()`) → `POST /api/projects/{pid}/suggest-terms`
   → `app.py` `api_suggest_terms()` (line 284) → `term_expansion.suggest_terms(cfg, term)`
   (`term_expansion.py` line 103).
2. **This IS an LLM call.** `suggest_terms()` calls `call = call_fn or (lambda p, m:
   __import__("analysis").call_claude(p, m, max_tokens=1500))` (`term_expansion.py` inside
   `suggest_terms`) and `analysis.call_claude()` (`analysis.py` line 130) makes a real
   `anthropic` SDK request. The prompt (`term_expansion.build_prompt`, line 35) explicitly asks
   for: (a) product-variant phrases in the primary language, (b) real brand/shop names "actually
   present" in the configured market, and (c) a `translations` object with one entry per
   **other** configured language (line ~55-60: `other_languages = languages[1:]`), each carrying
   a translated base term plus up to 5 translated variants.
3. **Nothing is written yet.** `suggest_terms()` only returns the parsed candidate lists
   (`parse_expansion`, line 78) to the browser for a human to check/uncheck.
4. **Confirmation writes it in:** `POST /api/projects/{pid}/apply-terms` → `app.py`
   `api_apply_terms()` (line 304) → `term_expansion.apply_expansion()` (line 143), which creates
   one **new keyword structure key per confirmed item** (e.g. `coffee_variant_instant_coffee`,
   `coffee_brand_starbucks`, and for a translated Hindi entry, `coffee_translated` under
   `keywords.by_language["hi"]`) — then `app.py` immediately calls
   `config_mod.regenerate_news_feeds(new_cfg)` (line 322) so each new structure becomes its own
   News/Bing feed.
5. **Brands are also written to `competitors`** (`term_expansion.py` `apply_expansion`, the
   `competitors.append(b)` block) — meaning a term-expansion brand suggestion, once confirmed,
   also participates in `analysis.py`'s existing `brand_focus` LLM tagging category
   ("named competitor").

**Live-verified in this same session** (not re-derived here, cited from the just-completed
feature work in this conversation): running this against a real India/coffee project returned 12
genuine product variants, 12 real India-specific brands (Nescafé, Bru, CCD, Blue Tokai, Starbucks,
Café Coffee Day, Lavazza, Indian Coffee House, Araku, Twenty Third Street Coffee), and correct
native-script translations across all 8 non-English configured languages — and increased that
project's Google+Bing News feed count from 15+15 to 87+87.

### 1c. Fetching → processing → storage → return (shared by both entry points, once terms exist)

6. `jobs.enqueue()` → `jobs.run_collection()` → `scraper.collect(cfg, params)` (per channel).
7. Each channel builds its actual outbound URL(s) from the terms established above, fetches via
   `http_client.get_session()` (all channels except `ecommerce.py`, which drives Playwright), and
   applies its own relevance/market gate (News: `scrapers/news.py market_signal`, line 225; GDELT:
   re-validates titles against `relevance_terms` per `AUDIT_01`).
8. `storage.save_items()` computes a `content_hash`, enforces `UNIQUE(project_id, content_hash)`
   for dedup, and assigns a `cluster_id` for near-duplicate grouping.
9. Optionally, `analysis.analyze_batch()`/`analyze_all()` sends up to 12 stored items per Claude
   call for sentiment/summary/brand-focus/purchase-driver tagging (see AUDIT_04 for full AI
   architecture).
10. The browser (`static/app.js`) polls `/api/jobs/{id}`, then re-fetches
    `/api/projects/{pid}/dashboard` and `/api/projects/{pid}/items-table` to render results —
    there is no push/streaming channel back to the browser (confirmed: no websocket/SSE route
    exists anywhere in `app.py`).

---

## Section 2 — Query expansion audit

**Does the system discover related terms for a broad query like "coffee" automatically?**
**No, not automatically — Partial, opt-in only.** By default (Entry point A, the wizard),
"coffee" stays exactly "coffee" everywhere in the pipeline. Related terms (variants, spelling
neighbors, hashtags, competitor brands) are only added if a human explicitly runs the term-
expansion feature (Entry point B) and explicitly confirms which suggestions to keep. There is no
background/automatic expansion step anywhere in `jobs.run_collection` or any scraper's `collect()`
— confirmed by their full bodies containing no call into `term_expansion` or any synonym/thesaurus
logic.

**Multilingual expansion audit — Hindi, Tamil, Telugu, Bengali, Marathi, Kannada, Malayalam,
Gujarati, Punjabi, and other Indian languages, specifically:**
- **Native script:** `term_expansion.py`'s `translations` output is explicitly requested "how a
  native speaker would actually phrase it (a natural loanword/transliteration..., not a stilted
  literal dictionary translation)" (`build_prompt`, the "Rules" section) and is written to the
  correct language's keyword slot by `apply_expansion`. **This exists, but only via the opt-in
  LLM call — there is no static dictionary anywhere in the repo mapping English terms to Hindi/
  Tamil/Telugu/etc. equivalents** (confirmed: a repo-wide search for translation/dictionary data
  files finds none; `config.py`'s only language-related static data are `LANGUAGE_TABLE` — ISO
  code + English display name pairs, e.g. `{"code": "te", "name": "Telugu"}` — and
  `COUNTRY_TABLE["india"]["native_names"]`, which maps a language code to the *single word for
  "India"* in that language, e.g. `{"te": "భారత్"}` — this is used for the market-relevance
  filter, not for query expansion; see below).
- **Romanized/Hinglish, transliteration into Latin script, mixed-language queries, regional
  slang:** **UNKNOWN — not addressed by the prompt or the parser.** `term_expansion.build_prompt`
  asks for the term "in that language" without specifying script, and Claude's actual output
  observed live for Hindi used Devanagari script (कॉफी), not Romanized Hindi ("kaafi"). Whether a
  differently-worded prompt or a different `translations` field would surface Romanized/Hinglish
  variants is untested — this requires an actual runtime experiment (prompting for Romanized
  form explicitly), not something determinable from static code.
- **Regional slang:** **UNKNOWN — not solicited by the current prompt at all**; the prompt asks
  for "the base term" and "variants," with no slang/colloquialism instruction either way.

**Answering the four specific product questions, each Yes/No/Partial with evidence:**

- **"If a user types an English keyword, does the system return content that is NATIVELY written
  in Hindi/Bangla/Telugu/other — or only English-language content that happens to be about that
  keyword?"**
  **Partial — depends entirely on whether the user has (a) configured that language for the study
  at all, AND (b) either manually filled that language's keyword slot or run term-expansion and
  confirmed a translation for it.** If both conditions hold, News/Bing feeds are built with the
  literal translated term in that language's Google/Bing News edition (`hl=<lang>-<ISO>`), which
  returns genuinely native-language content — this was live-verified this session (real Telugu
  articles from tv9telugu.com, ETV Bharat, Andhrajyothy). If neither condition holds (the default,
  untouched wizard output), that language's `category_generic` slot is empty (Section 1a step 3)
  and **zero feeds are generated for it** — the system returns nothing in that language, not
  English-language content "about" the keyword translated. There is no fallback that translates
  an English query into every study language automatically.

- **"If the same concept has a different word/term in another language..., does the system detect
  that and search using the equivalent term automatically? Or does it only ever search the
  literal string typed in?"**
  **No, by default it only ever searches the literal string typed in.** Automatic detection/
  translation happens **only** if the user separately invokes and confirms `term_expansion.py`'s
  suggestions (Entry point B) — this is a manual, per-term, per-project action, not something that
  runs "automatically" as part of searching.

- **"Can a single query return results scoped to multiple countries/regions at once..., or is
  geography fixed per job/config?"**
  **No — geography is fixed to exactly ONE country per project, enforced server-side.**
  `app.py`'s `api_wizard()` explicitly rejects a `market.country` list with more than one entry
  (lines 204-207: `"A study targets exactly one country/region."`) and every downstream mechanism
  that depends on country (ccTLD, GDELT `sourcecountry`, Google/Bing News `gl`/gl-market params,
  the native-script market terms in `COUNTRY_TABLE`) is built from that single string. To collect
  India + Bangladesh + US in one project is architecturally not possible; it would require three
  separate projects.

- **"Is the term-expansion... driven by an LLM's semantic/contextual understanding at query time,
  or by a static hardcoded list, dictionary file, or lookup table? Cite the exact
  file/mechanism."**
  **Both exist, doing different jobs, and this distinction must not be conflated:**
  - The **default/automatic** relevance-term derivation that happens for every project with zero
    extra steps (`config.derive_relevance_terms`, `config.py` line 453) is a **static, purely
    mechanical string-split** — no LLM, no lookup table, just `.split()` on the category string.
    It does not generalize to unenumerated concepts at all; "coffee" never becomes "espresso"
    here.
  - The **opt-in** term-expansion feature (`term_expansion.suggest_terms`, `term_expansion.py`
    line 103) **is genuinely LLM-driven** — it makes a real Anthropic API call
    (`analysis.call_claude`) and the variants/brands/translations it returns come from the model's
    own knowledge, not a hardcoded list. Confirmed live: the model returned "espresso,"
    "cappuccino," "iced coffee," "black coffee" — terms that do not appear anywhere as literal
    strings in this codebase — so this mechanism does generalize to concepts nobody explicitly
    enumerated in code.
  - **Plainly stated:** the system is only AI-driven for query expansion **when a human explicitly
    asks it to be, one term at a time.** There is no LLM in the default, always-on path from
    intake to collection.

---

## Section 3 — Discovery vs. crawling

**Does the architecture distinguish finding content (A) from fetching (B) from processing (C)?**
**Yes, cleanly, at the type level.** Every channel's `collect(cfg, params) -> ScrapeResult`
(`scrapers/base.py`) is required to do all three internally and return only the final
`ScrapeResult` — but *within* that function, the three concerns are visibly separate code
sections in every channel inspected in Phase 1/3 (e.g. `scrapers/news.py`: iterate
`source_plan.google_news_feeds` [discovery] → `fetch(url)` via `http_client` [fetching] →
`relevance`/`market_signal` gating + text extraction [processing]). There is no shared
"discovery" module, however — each channel re-implements its own discovery loop independently
(confirmed by comparing `scrapers/news.py`, `scrapers/reddit.py`, `scrapers/ecommerce.py` — no
common discovery abstraction is imported by more than one of them beyond `scrapers/base.py`'s
trivial `relevance_terms()` helper).

**What is the actual discovery mechanism, per channel** (fuller detail deferred to AUDIT_03,
which is the phase explicitly scoped for a full per-source table; this section answers only the
discovery-mechanism-type question):
- **News:** a hosted search API/index (Google News RSS search, Bing News RSS search) PLUS direct
  RSS feeds the user pastes. Google/Bing News here function as a **search engine**, not a crawler
  MarketLens operates itself.
- **GDELT:** a hosted search API (DOC 2.0), same category as above.
- **Reddit:** Reddit's own `search.rss` (a hosted search endpoint) plus fixed `new.rss`/`top.rss`
  listing endpoints for user-configured subreddits — bounded to those specific subreddits, not a
  site-wide crawl.
- **YouTube / Google Business:** official hosted search APIs (`search.list`, Places text search).
- **Forums / Quora:** **no discovery at all** — the user must paste every specific thread/question
  URL individually; confirmed by reading both channels' `collect()` functions in full during this
  phase (`scrapers/forums.py`, `scrapers/quora.py`) — neither contains any link-extraction/
  link-following logic to find *additional* URLs beyond what was configured, only "next page"
  pagination *within* an already-given thread (`scrapers/forums.py`'s multi-language next-page
  link matching).
- **E-commerce:** user-pasted explicit URLs, or a `{q}`-template expanded against the configured
  keyword list (`build_search_urls`, `scrapers/ecommerce.py` line 129) — the template itself is
  user-authored, not discovered.
- **Trends:** not a discovery mechanism in the usual sense — it queries interest-over-time for a
  fixed keyword list, returning a number series, not a list of documents.

**Can the system discover content NOT in initial search results?** **No, not automatically, for
any channel.** Every channel's universe of results is bounded by what its one hosted-search-API
call (or its fixed listing endpoints) returns for the exact configured query — there is no
second-order "follow this result's links to find more" step anywhere in the codebase (confirmed
absent in every `collect()` function read during Phase 1/2). The closest thing to "beyond initial
results" is News's date-chunking (`chunk_date_ranges`, re-querying the *same* search across
narrower date windows to work around a single query's ~100-result ceiling — this is repeating the
same discovery mechanism with a narrower parameter, not a qualitatively different discovery path).

**Hard result limits identified in this phase, with citations** (full scale analysis is AUDIT_05's
explicit scope; these are the mechanisms, cited precisely):
- Google News / Bing News RSS: **an external, Google/Bing-side limit, not a MarketLens parameter**
  — `scrapers/news.py`'s own module docstring (line 6) documents it as "~100-results-per-query
  cap," worked around only by date-chunking (querying narrower windows), not by any `max_results`
  code parameter (confirmed: no such parameter exists in `scrapers/news.py`).
  - **Verified empirically in this session** (not a citation from static code, but from a real run
    logged in this conversation): every single Google News feed URL fetched during live testing
    returned `"entries": 100` when raw volume existed, consistently, across many different
    queries and languages — directly consistent with the documented external limit.
- GDELT: a **code-level, configurable** parameter — `maxrecords` defaults to 250
  (`scrapers/gdelt.py` line 89, `cfg.get("collection_settings", {}).get("gdelt_chunk_size", 250)`),
  overridable per-project via `collection_settings.gdelt_chunk_size`.
- Google Trends (pytrends): `keywords = keywords[:5]` — `scrapers/trends.py` line 57, a hard
  code-level cap of 5 keywords per request (a pytrends/Google Trends API constraint, enforced in
  code).
- Reddit, YouTube, Google Business, Forums, Quora, E-commerce: **UNKNOWN at this phase** whether
  each has its own additional per-request page-size/count limit beyond what its underlying API
  naturally returns — full source-by-source limits are AUDIT_03's explicit scope, not re-derived
  here to avoid duplicating that phase's table.

---

## Open questions for Phase 3

1. Full per-channel limit table (page sizes, max pages, per-request item counts) for Reddit,
   YouTube, Google Business, Forums, Quora, E-commerce — flagged above as deferred, not yet
   answered.
2. `http_client.py`'s exact retry/backoff numbers, and how they interact with each channel's own
   additional retry logic (e.g. `scrapers/reddit.py`'s `_fetch_with_429_retry`,
   `scrapers/trends.py`'s custom retry wrapper written because pytrends' own retry args crash).
3. Whether `scrapers/__init__.py`'s `CHANNEL_INFO` text has other stale method/limitation
   descriptions beyond the confirmed Reddit "public JSON" mismatch (AUDIT_01 Section 1) — needs a
   side-by-side check against each channel's actual current `collect()` body.
4. Proxy/IP architecture — not touched in this phase at all; is there any proxy configuration path
   in `scrapers/ecommerce.py` (which mentions "proxy recommended beyond light use" in
   `CHANNEL_INFO`) or elsewhere?
5. Anti-bot/CAPTCHA detection specifics per source (Quora's Cloudflare challenge and e-commerce's
   bot-wall detection were referenced via `CHANNEL_INFO` text in this phase, but their actual
   detection code — `scrapers/quora.py`, `scrapers/ecommerce.py` — has not yet been read in full).
