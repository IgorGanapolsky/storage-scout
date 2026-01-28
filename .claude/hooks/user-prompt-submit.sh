#!/bin/bash
# User Prompt Submit Hook - RLHF with LanceDB
# Detects thumbs up/down and records directly to LanceDB vector store
#
# ASYNC MODE: Uses async: true in settings.json for non-blocking execution

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEMANTIC_MEMORY="$SCRIPT_DIR/../scripts/feedback/semantic-memory.py"
FEEDBACK_SCRIPT="$SCRIPT_DIR/../scripts/feedback/capture-feedback.js"
MEMORY_DIR="$SCRIPT_DIR/../memory/feedback"
HOOK_LOG="$MEMORY_DIR/hook-log.jsonl"
VENV_PYTHON="$SCRIPT_DIR/../scripts/feedback/venv/bin/python3"

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

# Detect Python environment
get_python() {
  if [ -f "$VENV_PYTHON" ]; then
    echo "$VENV_PYTHON"
  elif command -v python3 &>/dev/null; then
    echo "python3"
  else
    echo ""
  fi
}

PYTHON_CMD=$(get_python)

# Detect thumbs up feedback
if echo "$USER_MESSAGE" | grep -qiE '(thumbs?\s*up|👍|\+1|good\s*job|great\s*work|perfect|excellent|amazing|awesome|well\s*done)'; then
  log_hook "feedback_detected" "positive"
  CONTEXT=$(echo "$USER_MESSAGE" | head -c 500)

  # Record to LanceDB via semantic-memory.py
  if [ -n "$PYTHON_CMD" ] && [ -f "$SEMANTIC_MEMORY" ]; then
    echo "Success pattern recorded" | "$PYTHON_CMD" "$SEMANTIC_MEMORY" \
      --add-feedback \
      --feedback-type positive \
      --feedback-context "$CONTEXT" 2>/dev/null
  fi

  # Fallback to JSON capture
  if [ -f "$FEEDBACK_SCRIPT" ]; then
    node "$FEEDBACK_SCRIPT" up "$CONTEXT" 2>/dev/null
  fi
fi

# Detect thumbs down feedback
if echo "$USER_MESSAGE" | grep -qiE '(thumbs?\s*down|👎|-1|wrong|incorrect|bad|mistake|error|failed|broken|bug|issue|problem)'; then
  log_hook "feedback_detected" "negative"
  CONTEXT=$(echo "$USER_MESSAGE" | head -c 500)

  # Record to LanceDB via semantic-memory.py
  if [ -n "$PYTHON_CMD" ] && [ -f "$SEMANTIC_MEMORY" ]; then
    echo "Negative feedback - needs investigation" | "$PYTHON_CMD" "$SEMANTIC_MEMORY" \
      --add-feedback \
      --feedback-type negative \
      --feedback-context "$CONTEXT" 2>/dev/null
  fi

  # Fallback to JSON capture
  if [ -f "$FEEDBACK_SCRIPT" ]; then
    node "$FEEDBACK_SCRIPT" down "$CONTEXT" 2>/dev/null
  fi
fi

# Pass through to Claude (don't block the prompt)
exit 0
