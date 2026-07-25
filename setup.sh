#!/usr/bin/env bash
# MarketLens non-Docker setup (macOS / Linux).
# Creates a venv, installs deps + the Playwright browser, and prints the run command.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
echo "==> Using $($PYTHON --version)"

if [ ! -d ".venv" ]; then
  echo "==> Creating virtual environment (.venv)"
  "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Upgrading pip"
pip install --quiet --upgrade pip

echo "==> Installing Python dependencies (this can take a few minutes)"
pip install -r requirements.txt

echo "==> Installing the Playwright Chromium browser (for e-commerce scraping)"
python -m playwright install chromium || {
  echo "    (Playwright browser install failed — e-commerce channel will be skipped, "
  echo "     everything else still works. Re-run 'python -m playwright install chromium' later.)"
}

if [ ! -f ".env" ]; then
  echo "==> Creating .env from .env.example (edit it to add API keys)"
  cp .env.example .env
fi

cat <<'EOF'

============================================================
 MarketLens is ready.

 Run it:
     source .venv/bin/activate
     python app.py

 Then open http://localhost:8000

 Run the tests:
     python -m pytest -q

 Team mode (shared server):
     MODE=team ADMIN_PASSWORD=choose-a-password SESSION_SECRET=long-random python app.py
============================================================
EOF
