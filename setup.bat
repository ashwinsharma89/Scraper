@echo off
REM MarketLens non-Docker setup (Windows).
REM Creates a venv, installs deps + the Playwright browser, prints the run command.
setlocal

cd /d "%~dp0"

echo ==^> Checking Python
python --version || (echo Python 3.11+ is required on PATH & exit /b 1)

if not exist ".venv" (
  echo ==^> Creating virtual environment (.venv)
  python -m venv .venv
)

call .venv\Scripts\activate.bat

echo ==^> Upgrading pip
python -m pip install --quiet --upgrade pip

echo ==^> Installing Python dependencies (this can take a few minutes)
pip install -r requirements.txt

echo ==^> Installing the Playwright Chromium browser
python -m playwright install chromium

if not exist ".env" (
  echo ==^> Creating .env from .env.example
  copy .env.example .env
)

echo.
echo ============================================================
echo  MarketLens is ready.
echo.
echo  Run it:
echo      .venv\Scripts\activate.bat
echo      python app.py
echo.
echo  Then open http://localhost:8000
echo.
echo  Run the tests:
echo      python -m pytest -q
echo.
echo  Team mode (shared server):
echo      set MODE=team ^&^& set ADMIN_PASSWORD=choose-a-password ^&^& set SESSION_SECRET=long-random ^&^& python app.py
echo ============================================================
endlocal
