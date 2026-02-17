#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

JOBS=()
PIDS=()
FAIL=0

pick_python() {
  local candidate=""
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
    then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

run_job() {
  local name="$1"
  shift
  JOBS+=("$name")
  (
    "$@"
  ) >"$TMP_DIR/$name.log" 2>&1 &
  PIDS+=("$!")
}

echo "[throughput-checks] running omx doctor (fast gate)..."
omx doctor >"$TMP_DIR/omx-doctor.log" 2>&1 || FAIL=1
cat "$TMP_DIR/omx-doctor.log"

if command -v ruff >/dev/null 2>&1; then
  run_job "ruff" ruff check autonomy/ --select E,F,W --ignore E501
else
  echo "[throughput-checks] ruff not found, skipping lint gate."
fi

PYTHON_BIN="$(pick_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "[throughput-checks] no compatible Python (>=3.10) found."
  exit 1
fi
echo "[throughput-checks] using $PYTHON_BIN for pytest"
run_job "pytest" "$PYTHON_BIN" -m pytest -q

for i in "${!JOBS[@]}"; do
  if ! wait "${PIDS[$i]}"; then
    FAIL=1
  fi
done

for name in "${JOBS[@]}"; do
  echo
  echo "[throughput-checks] ===== $name ====="
  cat "$TMP_DIR/$name.log"
done

if [[ "$FAIL" -ne 0 ]]; then
  echo "[throughput-checks] FAILED"
  exit 1
fi

echo
echo "[throughput-checks] PASSED"
