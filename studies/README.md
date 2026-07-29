# Studies (portable project archives)

`.mlz` files are MarketLens project archives (config + items + analysis + market intel +
run log). Import one into a running instance to continue the study:

    curl -X POST http://localhost:8000/api/archive/import -F "file=@studies/<file>.mlz"

- **maggi-malaysia.mlz** — Maggi / Malaysia study, market-filtered to Malaysia-only
  (40 items, all analyzed). Off-market (India/global) noise removed.
- **maggi-malaysia-2026.mlz** — "Maggi Malaysia 2026": full-year (all of 2026),
  monthly-chunked, market-filtered, de-duplicated, relevance-validated Malaysia-only
  study (27 items: news + GDELT, GDELT re-checked against relevance terms).

Both demonstrate a fully-populated, analyzed study end-to-end.
