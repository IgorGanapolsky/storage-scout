#!/bin/bash
# Session Start Hook - Lightweight bootstrap
# Uses ShieldCortex MCP for memory (Claude calls mcp__memory__get_context)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# === GitHub Account Auto-Switch ===
REQUIRED_GH_ACCOUNT="IgorGanapolsky"
CURRENT_ACCOUNT=$(gh auth status 2>&1 | grep "Active account: true" -B2 | grep "account" | head -1 | sed 's/.*account \([^ ]*\).*/\1/')

if [ "$CURRENT_ACCOUNT" != "$REQUIRED_GH_ACCOUNT" ]; then
  if gh auth switch --user "$REQUIRED_GH_ACCOUNT" 2>/dev/null; then
    echo "🔄 Switched GitHub account to $REQUIRED_GH_ACCOUNT"
  else
    echo "⚠️  Could not switch to $REQUIRED_GH_ACCOUNT - you may need to run: gh auth login"
  fi
fi

# === Pending Cortex Sync Check ===
PENDING_SYNC="$SCRIPT_DIR/../memory/feedback/pending_cortex_sync.jsonl"
if [ -f "$PENDING_SYNC" ] && [ -s "$PENDING_SYNC" ]; then
  COUNT=$(wc -l < "$PENDING_SYNC" | tr -d ' ')
  echo "⚠️  ACTION REQUIRED: Sync $COUNT pending feedback entries to Cortex"
  echo "   Read $PENDING_SYNC and call mcp__memory__remember for each"
fi

# === TruthGuard (Lite) ===
# Pull recent negative feedback / "lies" flags from local memory and print them
# so the agent sees them before answering.
REPO_ROOT="$SCRIPT_DIR/../.."
PYTHON_EXE="$REPO_ROOT/.venv/bin/python3.14"
if [ ! -x "$PYTHON_EXE" ]; then
  PYTHON_EXE="$(command -v python3 2>/dev/null)"
fi

if [ -n "$PYTHON_EXE" ] && [ -f "$REPO_ROOT/.claude/scripts/feedback/truth_rag_lite.py" ]; then
  "$PYTHON_EXE" "$REPO_ROOT/.claude/scripts/feedback/truth_rag_lite.py" --start-context 2>/dev/null || true
fi

# === Ralph State Recovery ===
RALPH_STATE="$SCRIPT_DIR/../RALPH_STATE.md"
if [ -f "$RALPH_STATE" ]; then
  LAST_STATUS=$(grep "^\*\*" "$RALPH_STATE" | head -1 | sed 's/\*//g' | xargs)
  [ -n "$LAST_STATUS" ] && echo "🤖 Ralph State: $LAST_STATUS"
fi

exit 0
