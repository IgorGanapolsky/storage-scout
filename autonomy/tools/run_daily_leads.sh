#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/ganapolsky_i/workspace/git/igor/storage"
ENV_FILE="$ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env at $ENV_FILE" >&2
  exit 1
fi

API_KEY=$(python3 - <<'PY'
from pathlib import Path
path = Path('/Users/ganapolsky_i/workspace/git/igor/storage/.env')
key = ""
for line in path.read_text().splitlines():
    if line.startswith('GOOGLE_PLACES_API_KEY='):
        key = line.split('=', 1)[1].strip()
        break
print(key)
PY
)

if [[ -z "$API_KEY" ]]; then
  echo "Missing GOOGLE_PLACES_API_KEY in .env" >&2
  exit 1
fi

export GOOGLE_PLACES_API_KEY="$API_KEY"
python3 "$ROOT/autonomy/tools/lead_gen_broward.py" --limit 30
