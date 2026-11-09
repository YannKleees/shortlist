@echo off
rem Start Shortlist on Windows. Creates a virtual environment on first run.
cd /d "%~dp0"
if not exist .venv (
  echo First run: setting up, about a minute
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\python -m pip install -q -e .
)
if not exist .env copy .env.example .env >nul
where ollama >nul 2>nul || echo Tip: install Ollama from https://ollama.com for motivation letters
.venv\Scripts\python -m shortlist %*
