#!/bin/bash
# User Prompt Submit Hook
# Detects thumbs up/down feedback and captures it automatically

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FEEDBACK_SCRIPT="$SCRIPT_DIR/../scripts/feedback/capture-feedback.js"
LESSON_SCRIPT="$SCRIPT_DIR/../scripts/feedback/auto-lesson-creator.js"
MEMORY_DIR="$SCRIPT_DIR/../memory/feedback"
HOOK_LOG="$MEMORY_DIR/hook-log.jsonl"

# Ensure memory directory exists
mkdir -p "$MEMORY_DIR"

# Read the user's message from stdin
USER_MESSAGE=$(cat)

# Function to log hook activity
log_hook() {
  local event="$1"
  local data="$2"
  local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  echo "{\"timestamp\":\"$timestamp\",\"event\":\"$event\",\"data\":\"$data\"}" >> "$HOOK_LOG"
}

# Detect thumbs up feedback
if echo "$USER_MESSAGE" | grep -qiE '(thumbs?\s*up|👍|\+1|good\s*job|great\s*work|perfect|excellent|amazing|awesome|well\s*done)'; then
  log_hook "feedback_detected" "positive"

  # Extract context (the message itself, truncated)
  CONTEXT=$(echo "$USER_MESSAGE" | head -c 500)

  # Capture feedback
  if [ -f "$FEEDBACK_SCRIPT" ]; then
    node "$FEEDBACK_SCRIPT" up "$CONTEXT" 2>/dev/null
  fi
fi

# Detect thumbs down feedback
if echo "$USER_MESSAGE" | grep -qiE '(thumbs?\s*down|👎|-1|wrong|incorrect|bad|mistake|error|failed|broken|bug|issue|problem)'; then
  log_hook "feedback_detected" "negative"

  # Extract context
  CONTEXT=$(echo "$USER_MESSAGE" | head -c 500)

  # Capture feedback
  if [ -f "$FEEDBACK_SCRIPT" ]; then
    node "$FEEDBACK_SCRIPT" down "$CONTEXT" 2>/dev/null
  fi

  # Auto-generate lessons from negative feedback
  if [ -f "$LESSON_SCRIPT" ]; then
    node "$LESSON_SCRIPT" process 2>/dev/null
  fi
fi

# Pass through to Claude (don't block the prompt)
exit 0
