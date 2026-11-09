#!/usr/bin/env sh
# Start Shortlist on macOS or Linux. Creates a virtual environment on first run.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: setting up (about a minute)"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -e .
fi
[ -f .env ] || cp .env.example .env
command -v ollama >/dev/null 2>&1 || echo "Tip: install Ollama from https://ollama.com for motivation letters"
exec .venv/bin/python -m shortlist "$@"
