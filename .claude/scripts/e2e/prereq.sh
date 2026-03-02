#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT_DIR"

if [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* || "${OSTYPE:-}" == win32* ]]; then
  echo "[e2e-prereq] Native Windows detected. Use WSL or adapt this script for native support."
  exit 1
fi

for cmd in python3 npx curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[e2e-prereq] missing required command: $cmd" >&2
    exit 1
  fi
done

npx --yes agent-browser --help >/dev/null
npx --yes agent-browser install >/dev/null

echo "[e2e-prereq] prerequisites OK"

