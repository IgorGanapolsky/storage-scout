#!/bin/bash
# User Prompt Submit Hook - RLHF via ShieldCortex MCP
# Queues thumbs up/down for Claude to sync via mcp__memory__remember
#
# ASYNC MODE: Uses async: true in settings.json for non-blocking execution

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="$SCRIPT_DIR/../memory/feedback"
PENDING_SYNC="$MEMORY_DIR/pending_cortex_sync.jsonl"

mkdir -p "$MEMORY_DIR"

USER_MESSAGE=$(cat)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Infer domain from context
infer_domain() {
  local ctx="$1"
  local lower=$(echo "$ctx" | tr '[:upper:]' '[:lower:]')

  [[ "$lower" =~ (sonar|snyk|codeql|security|ci|workflow) ]] && echo "ci" && return
  [[ "$lower" =~ (git|commit|push|pr|merge|branch) ]] && echo "github" && return
  [[ "$lower" =~ (api|http|request|endpoint) ]] && echo "api" && return
  [[ "$lower" =~ (test|spec|coverage) ]] && echo "testing" && return
  [[ "$lower" =~ (flutter|dart|widget|mobile) ]] && echo "flutter" && return
  [[ "$lower" =~ (rental|tool|inventory|booking) ]] && echo "business" && return
  [[ "$lower" =~ (linkedin|job|resume|apply) ]] && echo "career" && return
  echo "general"
}

# Queue feedback for Cortex sync (Claude will call mcp__memory__remember)
queue_feedback() {
  local signal="$1"
  local context="$2"
  local domain=$(infer_domain "$context")
  local intensity="0.5"

  # Stronger signals
  [[ "$context" =~ (amazing|excellent|perfect|critical|terrible|awful) ]] && intensity="0.9"
  [[ "$context" =~ (good|great|bad|wrong) ]] && intensity="0.7"

  echo "{\"timestamp\":\"$TIMESTAMP\",\"signal\":\"$signal\",\"intensity\":$intensity,\"domain\":\"$domain\",\"context\":\"$(echo "$context" | head -c 200 | tr '\n' ' ' | sed 's/"/\\"/g')\"}" >> "$PENDING_SYNC"

  echo "✅ ${signal^} feedback recorded: $signal"
}

# Detect thumbs up
if echo "$USER_MESSAGE" | grep -qiE '(thumbs?\s*up|👍|\+1|good\s*job|great\s*work|perfect|excellent|amazing|awesome|well\s*done)'; then
  queue_feedback "positive" "$USER_MESSAGE"
fi

# Detect thumbs down
if echo "$USER_MESSAGE" | grep -qiE '(thumbs?\s*down|👎|-1|wrong|incorrect|bad|mistake|error|failed|broken|bug|issue|problem)'; then
  queue_feedback "negative" "$USER_MESSAGE"
fi

# Ralph Mode detection (kept - useful for autonomous execution)
USER_MESSAGE_LOWER=$(echo "$USER_MESSAGE" | tr '[:upper:]' '[:lower:]')
RALPH_KEYWORDS="implement|add feature|create|refactor|rewrite|build|fix.*and|update.*and|overnight|autonomous|/ralph|ralph mode"
SINGLE_FILE_KEYWORDS="fix typo|fix this line|change this|in this file only|single file"

if ! echo "$USER_MESSAGE_LOWER" | grep -qiE "$SINGLE_FILE_KEYWORDS"; then
  if echo "$USER_MESSAGE_LOWER" | grep -qiE "$RALPH_KEYWORDS"; then
    TASK_DESC=$(echo "$USER_MESSAGE" | head -c 100 | tr '\n' ' ' | sed 's/[^a-zA-Z0-9 ]//g' | xargs)
    echo ""
    echo "🤖 RALPH MODE - Task: $TASK_DESC"
    echo "   Execute autonomously: branch → implement → test → PR"
  fi
fi

exit 0
