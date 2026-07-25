# Studies (portable project archives)

`.mlz` files are MarketLens project archives (config + items + analysis + market intel +
run log). Import one into a running instance:

    POST /api/archive/import   (multipart file upload)

or from the app once an Import button exists. See HANDOFF.md.

- **maggi-malaysia.mlz** — a Maggi / Malaysia news study (153 items, all analyzed),
  reconstructed from an Excel export. Demonstrates a fully-populated study end-to-end.
