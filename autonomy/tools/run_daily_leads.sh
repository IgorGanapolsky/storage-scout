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

LIMIT="${1:-120}"
CATEGORIES="${LEADGEN_CATEGORIES:-med spa,plumber,dentist,hvac,roofing,electrician,chiropractor,urgent care,pest control,storage facility,auto repair,physical therapy,veterinary clinic,family law}"
MARKET_FILE="${LEADGEN_MARKET_FILE:-$ROOT/autonomy/data/us_growth_markets.json}"
DEFAULT_STATE="${LEADGEN_DEFAULT_STATE:-FL}"
CURSOR_KEY="${LEADGEN_CURSOR_KEY:-us_growth_markets}"
OUTPUT_PATH="${LEADGEN_OUTPUT_PATH:-$ROOT/autonomy/state/leads_ai_seo_growth.csv}"

python3 "$ROOT/autonomy/tools/lead_gen_broward.py" \
  --limit "$LIMIT" \
  --categories "$CATEGORIES" \
  --markets "$MARKET_FILE" \
  --state "$DEFAULT_STATE" \
  --cursor-key "$CURSOR_KEY" \
  --output "$OUTPUT_PATH"
