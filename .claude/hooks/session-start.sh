#!/bin/bash
# Session Start Hook
# Injects lessons learned at the start of each session

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LESSONS_FILE="$SCRIPT_DIR/../memory/lessons-learned.md"
FEEDBACK_SUMMARY="$SCRIPT_DIR/../memory/feedback/feedback-summary.json"

# Check if lessons file exists and has content
if [ -f "$LESSONS_FILE" ] && [ -s "$LESSONS_FILE" ]; then
  echo "📚 Lessons Learned loaded. Review critical items before proceeding."

  # Show critical lessons count
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
