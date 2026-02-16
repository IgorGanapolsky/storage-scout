#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "[omx-bootstrap] root: $ROOT_DIR"

if ! command -v omx >/dev/null 2>&1; then
  echo "[omx-bootstrap] installing oh-my-codex..."
  npm install -g oh-my-codex
fi

echo "[omx-bootstrap] omx version:"
omx --version || true

echo "[omx-bootstrap] running omx setup..."
omx setup

echo "[omx-bootstrap] running omx doctor..."
omx doctor

echo "[omx-bootstrap] complete"
