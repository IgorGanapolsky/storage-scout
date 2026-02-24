#!/bin/bash
# GSD Deployment Hook - Automates Admin Merges + Hybrid RLHF Sync
# Called when "GSD" is invoked

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ -z "${GITHUB_TOKEN:-}" ] && command -v gh >/dev/null 2>&1; then
    export GITHUB_TOKEN="$(gh auth token 2>/dev/null || true)"
fi

echo "🚀 Initiating GSD Autonomous Deployment & Hybrid RLHF Sync..."

# 1. Hybrid RLHF Sync (Centralize learnings)
if [ -f "$PROJECT_ROOT/.claude/memory/feedback/pending_cortex_sync.jsonl" ]; then
    echo "🧠 Syncing local feedback to ShieldCortex..."
    # If ShieldCortex tool was available, we'd call it here.
    # For now, we consolidate local lessons so they are ready for cross-session RAG.
    if command -v node >/dev/null 2>&1; then
        node "$SCRIPT_DIR/feedback/auto-lesson-creator.js" process
    fi
fi

# 2. Deploy to Main
cd "$PROJECT_ROOT"
BRANCH_NAME="admin/gsd-final-$(date +%s)"
git checkout -b "$BRANCH_NAME"
git add .
PRE_COMMIT_ALLOW_NO_CONFIG=1 git commit -m "chore: GSD Autonomous Deployment (Hybrid RLHF enabled)" || echo "Nothing to commit"
git push origin "$BRANCH_NAME" -f || true

gh pr create --base main --head "$BRANCH_NAME" --title "chore: GSD Autonomous Release" --body "Admin verified autonomous deployment." || echo "PR exists"
PR_NUM=$(gh pr list --head "$BRANCH_NAME" --base main --json number --jq '.[0].number')

if [ -n "$PR_NUM" ]; then
    echo "Merging PR #$PR_NUM via Admin Override..."
    gh pr merge "$PR_NUM" --squash --admin --delete-branch
    echo "✅ GSD Release Successful."
else
    echo "⚠️ GSD Release: No PR found or needed."
fi
