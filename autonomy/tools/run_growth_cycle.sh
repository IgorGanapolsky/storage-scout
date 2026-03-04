#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIMIT="${1:-120}"

"$ROOT/autonomy/tools/run_daily_leads.sh" "$LIMIT"
python3 "$ROOT/autonomy/run.py" --config "$ROOT/autonomy/config.ai-seo.json"
