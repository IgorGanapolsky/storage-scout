#!/bin/bash
# Session Start Hook
# Injects lessons and semantic context at the start of each session
# Also ensures correct GitHub account is active for this project

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# === GitHub Account Auto-Switch ===
# This project requires IgorGanapolsky account
REQUIRED_GH_ACCOUNT="IgorGanapolsky"
CURRENT_ACCOUNT=$(gh auth status 2>&1 | grep "Active account: true" -B2 | grep "account" | head -1 | sed 's/.*account \([^ ]*\).*/\1/')

if [ "$CURRENT_ACCOUNT" != "$REQUIRED_GH_ACCOUNT" ]; then
  if gh auth switch --user "$REQUIRED_GH_ACCOUNT" 2>/dev/null; then
    echo "🔄 Switched GitHub account to $REQUIRED_GH_ACCOUNT"
  else
    echo "⚠️  Could not switch to $REQUIRED_GH_ACCOUNT - you may need to run: gh auth login"
  fi
else
  echo "✅ GitHub: $REQUIRED_GH_ACCOUNT (active)"
fi
SEMANTIC_MEMORY="$SCRIPT_DIR/../scripts/feedback/semantic-memory.py"
LESSONS_FILE="$SCRIPT_DIR/../memory/lessons-learned.md"
FEEDBACK_SUMMARY="$SCRIPT_DIR/../memory/feedback/feedback-summary.json"

# Check if semantic memory is available and indexed
if [ -f "$SEMANTIC_MEMORY" ]; then
  # Check if LanceDB is indexed
  if [ -d "$SCRIPT_DIR/../memory/feedback/lancedb" ]; then
    python3 "$SEMANTIC_MEMORY" --context 2>/dev/null
  else
    echo "📊 LanceDB not indexed. Run: python .claude/scripts/feedback/semantic-memory.py --index"
  fi
fi

# Fallback: Check lessons file
if [ -f "$LESSONS_FILE" ] && [ -s "$LESSONS_FILE" ]; then
  CRITICAL_COUNT=$(grep -c "🚨" "$LESSONS_FILE" 2>/dev/null || echo "0")
  if [ "$CRITICAL_COUNT" -gt 0 ]; then
    echo "⚠️  $CRITICAL_COUNT critical lesson(s) to remember."
  fi
fi

# Show feedback stats if available
if [ -f "$FEEDBACK_SUMMARY" ]; then
  TOTAL=$(cat "$FEEDBACK_SUMMARY" | grep -o '"totalFeedback":[0-9]*' | grep -o '[0-9]*')
  POSITIVE=$(cat "$FEEDBACK_SUMMARY" | grep -o '"positive":[0-9]*' | head -1 | grep -o '[0-9]*')

  if [ -n "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then
    RATE=$(echo "scale=1; $POSITIVE * 100 / $TOTAL" | bc 2>/dev/null || echo "N/A")
    echo "📊 RLHF Stats: $POSITIVE/$TOTAL positive ($RATE% success rate)"
  fi
fi

exit 0
