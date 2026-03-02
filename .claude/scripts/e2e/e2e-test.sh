#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT_DIR"

PORT="${E2E_PORT:-4173}"
BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:${PORT}}"
SESSION="cc-e2e-$(date +%s)-$$"
SOCKET_PATH="${HOME}/.agent-browser/${SESSION}.sock"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="${ROOT_DIR}/.claude/artifacts/e2e/${STAMP}"
SERVER_LOG="${OUT_DIR}/server.log"
REPORT_MD="${OUT_DIR}/report.md"
SUMMARY_TXT="${OUT_DIR}/summary.txt"
SERVER_PID=""

mkdir -p "$OUT_DIR"

cleanup() {
  set +e
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  npx --yes agent-browser --session "$SESSION" close >/dev/null 2>&1 || true
  rm -f "$SOCKET_PATH" >/dev/null 2>&1 || true
}
trap cleanup EXIT

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[e2e] missing required command: $cmd" >&2
    exit 1
  fi
}

ab() {
  npx --yes agent-browser --session "$SESSION" "$@"
}

wait_for_url() {
  local url="$1"
  local retries=30
  local i
  for ((i=1; i<=retries; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

assert_url_contains() {
  local needle="$1"
  local current
  current="$(ab get url | tail -n 1)"
  if [[ "$current" != *"$needle"* ]]; then
    echo "[e2e] expected url to contain '$needle' but got '$current'" >&2
    return 1
  fi
  return 0
}

PASS_COUNT=0
FAIL_COUNT=0
CASE_LINES=()

run_case() {
  local id="$1"
  local name="$2"
  local fn="$3"
  local screenshot="${OUT_DIR}/${id}-${name}.png"

  echo "[e2e] running ${id}: ${name}"
  if "$fn" "$screenshot"; then
    PASS_COUNT=$((PASS_COUNT + 1))
    CASE_LINES+=("| ${id} | ${name} | PASS | ${id}-${name}.png |")
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    ab screenshot "${OUT_DIR}/${id}-${name}-FAIL.png" >/dev/null 2>&1 || true
    CASE_LINES+=("| ${id} | ${name} | FAIL | ${id}-${name}-FAIL.png |")
  fi
}

case_01_home_load() {
  local shot="$1"
  ab open "${BASE_URL}/callcatcherops/"
  ab wait 1000
  local title
  title="$(ab get title | tail -n 1)"
  [[ "$title" == *"CallCatcher Ops"* ]]
  ab screenshot "$shot"
}

case_02_home_to_intake() {
  local shot="$1"
  ab open "${BASE_URL}/callcatcherops/"
  ab wait 600
  ab click 'a[data-cta="hero_pilot"]'
  ab wait 900
  assert_url_contains "/callcatcherops/intake.html"
  ab screenshot "$shot"
}

case_03_home_to_subscription() {
  local shot="$1"
  ab open "${BASE_URL}/callcatcherops/"
  ab wait 600
  ab click 'a[data-cta="hero_subscription"]'
  ab wait 900
  assert_url_contains "/callcatcherops/workflow-subscription.html"
  ab screenshot "$shot"
}

case_04_home_to_crawl_offer() {
  local shot="$1"
  ab open "${BASE_URL}/callcatcherops/"
  ab wait 600
  ab click 'a[data-cta="hero_crawl_offer"]'
  ab wait 900
  assert_url_contains "/callcatcherops/ai-crawl-monetization.html"
  ab screenshot "$shot"
}

case_05_crawl_offer_to_assessment() {
  local shot="$1"
  ab open "${BASE_URL}/callcatcherops/ai-crawl-monetization.html"
  ab wait 600
  ab click 'a[data-cta="hero_assessment"]'
  ab wait 900
  assert_url_contains "/callcatcherops/assessment.html"
  ab screenshot "$shot"
}

case_06_workflow_nav_to_crawl_offer() {
  local shot="$1"
  ab open "${BASE_URL}/callcatcherops/workflow-subscription.html"
  ab wait 600
  ab click 'a[data-cta="nav_crawl_offer"]'
  ab wait 900
  assert_url_contains "/callcatcherops/ai-crawl-monetization.html"
  ab screenshot "$shot"
}

case_07_thanks_to_subscription() {
  local shot="$1"
  ab open "${BASE_URL}/callcatcherops/thanks.html"
  ab wait 600
  ab click '#cta-subscription'
  ab wait 900
  assert_url_contains "/callcatcherops/workflow-subscription.html"
  ab screenshot "$shot"
}

echo "[e2e] output dir: ${OUT_DIR}"
require_cmd bash
"${ROOT_DIR}/.claude/scripts/e2e/prereq.sh"
rm -f "$SOCKET_PATH" >/dev/null 2>&1 || true
npx --yes agent-browser --session "$SESSION" close >/dev/null 2>&1 || true

echo "[e2e] starting local docs server on ${BASE_URL}"
python3 -m http.server "$PORT" --directory docs >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

if ! wait_for_url "${BASE_URL}/callcatcherops/"; then
  echo "[e2e] server did not become ready; see ${SERVER_LOG}" >&2
  exit 1
fi

run_case "01" "home-load" "case_01_home_load"
run_case "02" "home-to-intake" "case_02_home_to_intake"
run_case "03" "home-to-subscription" "case_03_home_to_subscription"
run_case "04" "home-to-crawl-offer" "case_04_home_to_crawl_offer"
run_case "05" "crawl-offer-to-assessment" "case_05_crawl_offer_to_assessment"
run_case "06" "workflow-nav-to-crawl-offer" "case_06_workflow_nav_to_crawl_offer"
run_case "07" "thanks-to-subscription" "case_07_thanks_to_subscription"

{
  echo "# CallCatcher Ops E2E Report"
  echo
  echo "- Timestamp: ${STAMP}"
  echo "- Base URL: ${BASE_URL}"
  echo "- Session: ${SESSION}"
  echo "- Pass: ${PASS_COUNT}"
  echo "- Fail: ${FAIL_COUNT}"
  echo
  echo "| Case | Journey | Status | Artifact |"
  echo "| --- | --- | --- | --- |"
  for line in "${CASE_LINES[@]}"; do
    echo "$line"
  done
  echo
  echo "## Artifacts"
  echo "- Server log: \`server.log\`"
  echo "- Screenshots: \`*.png\`"
} >"$REPORT_MD"

{
  echo "pass=${PASS_COUNT}"
  echo "fail=${FAIL_COUNT}"
  echo "report=${REPORT_MD}"
  echo "artifacts=${OUT_DIR}"
} >"$SUMMARY_TXT"

echo "[e2e] pass=${PASS_COUNT} fail=${FAIL_COUNT}"
echo "[e2e] report=${REPORT_MD}"
echo "[e2e] artifacts=${OUT_DIR}"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi
