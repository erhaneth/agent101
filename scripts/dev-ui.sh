#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Missing .venv. Create it and install requirements first."
  exit 1
fi

source .venv/bin/activate
pip install -q -r requirements.txt

if [[ ! -d ui/node_modules ]]; then
  (cd ui && npm install)
fi

trap 'kill 0' EXIT
(cd ui && npm run dev) &
.venv/bin/uvicorn app:app --reload --host 127.0.0.1 --port 8000