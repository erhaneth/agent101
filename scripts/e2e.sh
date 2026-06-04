#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
E2E_DIR="${ROOT_DIR}/tmp/e2e"

rm -rf "$E2E_DIR"
mkdir -p "$E2E_DIR"

export AUTH_REQUIRED=false
export JOB_EXECUTION_MODE=external
export AUTH_DB_PATH="${E2E_DIR}/auth.db"
export JOB_DB_PATH="${E2E_DIR}/jobs.db"
export ARTIFACT_DB_PATH="${E2E_DIR}/artifacts.db"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/seed_e2e.py"

cd "$ROOT_DIR/ui"
npm run test:e2e
