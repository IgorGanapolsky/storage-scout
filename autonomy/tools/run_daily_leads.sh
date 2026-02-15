#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env at $ENV_FILE" >&2
  exit 1
fi

set -o allexport
# shellcheck disable=SC1090
source "$ENV_FILE"
set +o allexport

if [[ -z "${GOOGLE_PLACES_API_KEY:-}" ]]; then
  echo "Missing GOOGLE_PLACES_API_KEY in $ENV_FILE" >&2
  exit 1
fi

LIMIT="${1:-30}"
CATEGORIES="${LEADGEN_CATEGORIES:-med spa,plumber,dentist,hvac,roofing,electrician,chiropractor,urgent care,pest control}"
python3 "$ROOT/autonomy/tools/lead_gen_broward.py" --limit "$LIMIT" --categories "$CATEGORIES" --output "$ROOT/autonomy/state/leads_callcatcherops_real.csv"
