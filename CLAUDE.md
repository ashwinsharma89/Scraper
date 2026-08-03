# CLAUDE.md — MarketLens

Auto-loaded by Claude Code each session. Keep it short & high-signal. **Full engineering
handoff is in `HANDOFF.md` — read it once at the start of a new continuation.** Product
overview is in `README.md`.

## What this is
Local-first market & product intelligence tool. Python 3.11+ / FastAPI / SQLite (WAL) /
vanilla-JS SPA in `/static` (no build step). Pipeline the whole app is organized around:
**Configure (wizard) → Collect (scrapers) → Analyze (Claude) → Export (Excel + report).**

## Non-negotiable principles (this IS the product)
1. **Never fabricate or simulate data.** On failure, surface the error honestly, store nothing.
2. **No hard-coding** of brand / product / category / country / language — all from config.
3. **Tests mock all network; keep the suite green** after every change.
4. **Secrets from `.env` only** — never committed, never in the DB in plaintext.
5. **Precision over volume** — a keyword in a page's related-links footer is not a hit;
   content is validated (`scrapers/relevance.py`).

## Commands
```bash
source .venv/bin/activate
python -m pytest -q          # 125 tests, ~1.3s, network mocked — MUST stay green
python app.py                # http://localhost:8000
python seed_demo.py          # recreate the Acme Cola / Singapore demo
# reset local data after a run:
pkill -f "app.py"; rm -rf data && python seed_demo.py
```
If you hit `ModuleNotFoundError`, run `pip install -r requirements.txt` (the venv may lack
heavy deps: anthropic, playwright, pytrends, Pillow, python-docx). Port 8000 busy →
`lsof -ti:8000 | xargs kill -9`.

## Do NOT "fix" these (they are honest limitations, not bugs)
- **Google News article bodies are unresolvable** (encrypted URL token) — don't build a GN
  de-obfuscator. Already mitigated (not eliminated) by direct RSS feeds AND the Bing News
  channel, both of which resolve via normal redirects and carry real first-paragraph text.
- **Quick-commerce & most social are app-only / anti-automation → Tier-3 gaps**, never
  scrapers. This is permanent and deliberate — not one of the "structural gaps" to fix.
- Reddit/GDELT may 403/429 from some IPs — handled as honest partial failures.
- GDELT's own relevance matching is loose; `scrapers/gdelt.py` re-validates titles against
  relevance terms before storing. Its real yield for a narrow brand+country query is small
  by nature (broad event index, not a brand-review source) — that's not a bug to chase.

## Conventions
- Lazy-import heavy optional deps (so tests/base app don't require them).
- Add a pytest for every behavior change. Match the surrounding code's dense-but-commented style.
- Migrations (`migrations.py`) are append-only. `version.py` is the single version source.
- After local runs that write data, reset to the pristine demo (above).
- **Before touching the DB schema or a load-bearing design choice, read `HANDOFF.md`
  §10 (data model) & §11 (design rationale). If you change one, update that section — keep
  the docs living.** Before UX/feature calls, skim §13 (user context & priorities).

## Where to pick up
Pending work is `HANDOFF.md` §7. Ask the user which to prioritize before starting.

## ⚠ Security
A real Anthropic API key was pasted into a prior chat and must be treated as compromised.
Use a freshly generated key in `.env`; never paste keys into chat.
