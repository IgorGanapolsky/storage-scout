#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

# Load credentials
source .env

# Check business hours (9am-5pm ET)
hour=$(TZ=America/New_York date +%H)
if (( hour < 9 || hour >= 17 )); then
  echo "Outside business hours (9am-5pm ET). Exiting."
  exit 0
fi

echo "Starting Monday audit batch at $(date)"

# Array of dental offices to audit (from autonomy_live.sqlite3, ordered by score DESC)
# Format: "phone|company|service"
offices=(
  "+19544562100|DS DENTAL CARE|dentist"
  "+19544581133|Hallandale Beach Dental|dentist"
  "+19549982099|Dental Clinic Village of Dentistry Hallandale Beach|dentist"
  "+17864404948|The World of Dentistry|dentist"
  "+19547995807|Sage Dental of Hallandale Beach|dentist"
  "+19544544949|Hallandale Beach Dental Group|dentist"
  "+19544578288|Hallandale Dental Care|dentist"
  "+19544553434|Center for Dental Implants of Hallandale Beach|dentist"
  "+13054266422|ICONICA DENTAL GROUP OF HALLANDALE|dentist"
  "+19544561939|Bright Smiles by Dr. Vera Family and Cosmetic Dentistry|dentist"
)

LOG="autonomy/state/audit_batch_results.log"
mkdir -p autonomy/state

echo "Audit batch started at $(date)" >> "$LOG"

count=0
for entry in "${offices[@]}"; do
  IFS='|' read -r phone company service <<< "$entry"
  echo "Auditing: $company ($phone)"
  echo "--- Auditing: $company ($phone) at $(date) ---" >> "$LOG"

  python3 -m autonomy.tools.missed_call_audit \
    --phone "$phone" --company "$company" \
    --service "$service" --calls 3 --delay 0 \
    2>&1 | tee -a "$LOG"

  count=$((count + 1))

  if (( count < ${#offices[@]} )); then
    echo "Waiting 60s before next call..."
    sleep 60
  fi
done

echo ""
echo "Audit batch complete at $(date). $count offices audited."
echo "Audit batch complete at $(date). $count offices audited." >> "$LOG"

echo ""
echo "Generated HTML reports:"
ls -la autonomy/state/audit_*.html 2>/dev/null || echo "(no HTML reports found yet)"
