#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python || ! -d frontend/node_modules ]]; then
  if [[ "${1:-}" == '--offline' ]]; then
    echo 'Dependencies are missing. Run ./scripts/setup.sh once while online.' >&2
    exit 1
  fi
  ./scripts/setup.sh
fi
salmon_port="$(.venv/bin/python -c 'from backend.app.config import settings; print(settings.backend_port)')"
export NEXT_PUBLIC_BACKEND_URL="${NEXT_PUBLIC_BACKEND_URL:-http://localhost:$salmon_port}"
export NEXT_TELEMETRY_DISABLED=1
salmon_backend_pid=''
salmon_frontend_pid=''
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$salmon_backend_pid" ]] || kill "$salmon_backend_pid" 2>/dev/null || true
  [[ -z "$salmon_frontend_pid" ]] || kill "$salmon_frontend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$salmon_port" &
salmon_backend_pid=$!
(cd frontend && exec node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3000) &
salmon_frontend_pid=$!
echo "SalmonSight — http://localhost:3000 · API http://localhost:$salmon_port/docs"
while kill -0 "$salmon_backend_pid" 2>/dev/null && kill -0 "$salmon_frontend_pid" 2>/dev/null; do
  sleep 1
done
exit 1
