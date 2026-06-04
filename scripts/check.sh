#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

cd "$ROOT_DIR"

export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false
export LANGSMITH_API_KEY=""

"$PYTHON_BIN" -m unittest discover -s tests
"$PYTHON_BIN" -m compileall -q team web evals scripts app.py agent.py worker.py

cd "$ROOT_DIR/ui"
npm run lint
npm run build

if [[ "${RUN_E2E:-0}" == "1" ]]; then
  "$ROOT_DIR/scripts/e2e.sh"
fi
