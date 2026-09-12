#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  echo 'Install Node.js 20.9+ and npm, then rerun ./scripts/setup.sh.' >&2
  exit 1
fi
if command -v uv >/dev/null; then
  if [[ ! -x .venv/bin/python ]]; then uv venv --python 3.11 .venv; fi
  uv pip install --python .venv/bin/python -r backend/requirements.lock
else
  salmon_python="$(command -v python3.11 || command -v python3 || true)"
  if [[ -z "$salmon_python" ]] || ! "$salmon_python" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then
    echo 'Install Python 3.11+ or uv, then rerun ./scripts/setup.sh.' >&2
    exit 1
  fi
  if [[ ! -x .venv/bin/python ]]; then "$salmon_python" -m venv .venv; fi
  .venv/bin/python -m pip install -r backend/requirements.lock
fi
if [[ ! -f .env ]]; then cp .env.example .env; fi
npm --prefix frontend ci
echo 'Setup complete. Run ./scripts/dev.sh (or ./scripts/dev.sh --offline).'
