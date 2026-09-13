# AUDIT_08 — Empirical Volume Ceiling Test

Follow-up to AUDIT_07 §1, which left open "whether [full expansion] can reliably reach
10,000–40,000 in practice for a real topic." This phase answers that with a real, executed test
against a live project — not an estimate. No code was changed to run this test; every feature
exercised already existed (`term_expansion.py`, `config.regenerate_news_feeds`, the standard
collection pipeline).

---

## Test setup

- **Project:** #14, category-only study (no single target brand), category = "coffee"
- **Market:** India, single country (per the confirmed one-country-per-study constraint, AUDIT_02 §2)
- **Languages:** 9 — en, gu, hi, kn, ml, mr, pa, ta, te
- **Expansion applied at full strength:**
  - English: 12 product-variant structures (instant coffee, cold coffee, filter coffee,
    cappuccino, latte, espresso, americano, iced coffee, black coffee, coffee powder, cold brew,
    coffee beans) + 12 real, India-specific brand structures (Nescafé, Bru, CCD, Blue Tokai,
    Starbucks, Café Coffee Day, Lavazza, Davidoff, Philips, Indian Coffee House, Araku, Twenty
    Third Street Coffee) + the original category term = 31 English structures, all AI-generated
    via `term_expansion.suggest_terms()` and confirmed via `apply_expansion()`, not hand-typed
  - Each of the other 8 languages: a translated base term + 5 translated variants = 7 structures
    per language × 8 = 56 structures
  - **Total: 87 keyword structures → 174 feeds** (87 Google News + 87 Bing News), confirmed via
    `config.regenerate_news_feeds()` before running anything (the exact "confirm feed count
    actually changed" step this test plan required, to rule out the known
    edit-keywords-doesn't-regenerate-feeds bug from AUDIT_01/06)
  - All 12 brand names were also written to `competitors` for downstream analysis tagging

## Channels run

News, GDELT, Reddit, Trends — all four real, already-configured channels for this project.
E-commerce (no URLs configured), YouTube, Google Business (no API keys configured) were not run —
they would have been instant no-ops, not a meaningful volume test.

## Results

| Metric | Value |
|---|---|
| Total feeds generated | **174** (87 Google News + 87 Bing News) |
| Total feed fetches, this run | 1,131 (News: 87 structures × up to 12 monthly chunks + 87 non-chunked Bing feeds) |
| Raw candidates returned — News | 20,042 |
| Kept after relevance/market filter — News | 552 |
| Raw / kept — GDELT | 0 / 0 — **every monthly chunk hit HTTP 429** |
| Raw / kept — Reddit | 191 returned / 103 new (this run) — 6 of ~18 subreddit queries + several comment fetches hit 429 |
| Raw / kept — Trends | 104 returned / 76 new — succeeded this run (the IP-level block documented earlier this session had cleared) |
| New items this run, all 4 channels | 261 (news) + 0 (gdelt) + 103 (reddit) + 76 (trends) = **440** |
| **Total items, whole project (all runs, cumulative)** | **1,118** |
| **Deduplicated unique stories (`total_stories`, syndication-adjusted)** | **928** |
| Total elapsed time | 46 min 14 s (11:10:57 → 11:57:11 UTC) |
| Errors / dropped | News: 6,290 items dropped as off-market (expected for a generic global term in an India-scoped study). GDELT: 100% blocked. Reddit: 9 distinct 429s logged, remainder succeeded |

### Breakdown by language (News — the volume driver)

| Language | Feeds | Raw entries | Kept |
|---|---|---|---|
| en | 372 | 15,726 | 268 |
| hi | 84 | 1,726 | 131 |
| te | 84 | 912 | 40 |
| mr | 84 | 625 | 33 |
| ta | 84 | 273 | 3 |
| ml | 84 | 222 | 7 |
| pa | 84 | 48 | 1 |
| gu | 84 | 99 | 11 |
| kn | 84 | 0 | 0 |
| bing (all languages) | 87 | 411 | 58 |

### Cumulative breakdown by source (whole project, all runs to date)

| Source | Total items |
|---|---|
| News | 727 |
| Reddit | 315 |
| Trends | 76 |
| GDELT | 0 |
| **Total** | **1,118** |

## Verdict

**928 unique stories, 1,118 raw items — not 10,000–40,000.** Full legitimate use of every
already-built expansion feature at full strength lands in the **high hundreds to low thousands**,
matching AUDIT_06/07's "plateaus in the low-to-mid thousands" branch, not the "wire it up and
you're structurally already there" branch.

**The direct cause, proven empirically, not assumed:** adding query variants has already hit steep
diminishing returns. Going from 15+15 feeds → 87+87 feeds (5.8x more feeds) only moved News's kept
count from 378 → 552 (1.5x) — most of the added structures re-cover ground already found by other
structures rather than opening new content. **This specific lever (more variants/languages/brands)
is close to exhausted for this topic/market and should not be pushed further as the primary path
to higher volume.**

## What would actually move the number toward 30,000, ranked by leverage

1. **Disable the market filter (`market_only=false`) — the single largest available lever, a
   config flag, zero code change.** 6,290 of 20,042 raw News entries this run were dropped purely
   for lacking a provable India-specific signal, not for being irrelevant to coffee. Estimated
   effect: News kept count could rise from 552 toward ~6,800 in a single run (~12x) — **not yet
   empirically tested; the estimate is extrapolated from the drop count, and testing it directly
   was offered but not yet run.** The direct tradeoff: trading market-specificity for volume —
   global coffee news would flow in un-filtered by country.
2. **Activate YouTube and Google Business** (both require an API key not currently configured
   for this project) — plausible hundreds-to-low-thousands of additional items given the same
   already-expanded keyword set; an account/billing step, not a code change.
3. **Manually curate real Forum thread URLs** — Forums has zero discovery (AUDIT_02 §3); volume
   here scales with hours spent pasting real thread URLs, not with any code or config change.
4. **Run this configuration on a recurring schedule (already-built `scheduler.py`) over weeks or
   months** rather than as one backfill attempt — sidesteps same-day rate-limit walls (GDELT/
   Reddit) entirely and accumulates genuinely new content as it's published in the real world.
5. **What does NOT help, proven by this test:** more keyword/brand/translation variants beyond
   what's already applied (diminishing returns, above); retrying GDELT/Reddit/E-commerce more
   aggressively (they are actively blocking, not under-fetched — more requests make it worse);
   Quora or E-commerce beyond catalog-level pages (permanently blocked, no lever short of
   defeating anti-bot measures, which is out of scope).

**Combined, conservative estimate without any redesign:** relaxed market filter + YouTube
activated + a few months of recurring scheduled collection plausibly lands in the **5,000–15,000**
range — a large real jump from 928, but likely still short of 30,000 as an on-demand, single-run
number. Reliably clearing 30,000 **on demand** would require the redesign conversation from
AUDIT_06 (proxy infrastructure, async/distributed collection) specifically to sustain Reddit/
GDELT/E-commerce at volume without tripping their blocks — though it's worth noting those three
channels contributed under 200 items combined even when *not* blocked in this test, so that
redesign would need to be paired with lever #1 (market filter) to be worth the investment; fixing
the blocked channels alone would not reach 30,000 either.
