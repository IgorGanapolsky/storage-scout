#!/bin/bash
# User Prompt Submit Hook - RLHF via ShieldCortex MCP
# Queues thumbs up/down for Claude to sync via mcp__memory__remember
#
# ASYNC MODE: Uses async: true in settings.json for non-blocking execution

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="$SCRIPT_DIR/../memory/feedback"
PENDING_SYNC="$MEMORY_DIR/pending_cortex_sync.jsonl"
PENDING_STRATEGY="$MEMORY_DIR/pending_strategy_questions.jsonl"

mkdir -p "$MEMORY_DIR"

USER_MESSAGE=$(cat)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Infer domain from context
infer_domain() {
  local ctx="$1"
  local lower=$(echo "$ctx" | tr '[:upper:]' '[:lower:]')

  [[ "$lower" =~ (callcatcher|fastmail|imap|launchd|stripe|calendly|outreach|lead|leads|bounce|bounces|reply|replies|booking|bookings|daily[[:space:]]report) ]] && echo "callcatcherops" && return
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

queue_strategy_question() {
  local question="$1"
  local domain=$(infer_domain "$question")
  local priority="normal"
  [[ "$question" =~ (money|revenue|first[[:space:]]dollar|urgent|demand|make[[:space:]]money) ]] && priority="high"

  echo "{\"timestamp\":\"$TIMESTAMP\",\"domain\":\"$domain\",\"priority\":\"$priority\",\"question\":\"$(echo "$question" | head -c 400 | tr '\n' ' ' | sed 's/"/\\"/g')\"}" >> "$PENDING_STRATEGY"
  echo "📌 Strategy question queued for truth-loop analysis"
}

# Detect thumbs up
if echo "$USER_MESSAGE" | grep -qiE '(thumbs?\s*up|👍|\+1|good\s*job|great\s*work|perfect|excellent|amazing|awesome|well\s*done)'; then
  queue_feedback "positive" "$USER_MESSAGE"
fi

# Detect thumbs down
if echo "$USER_MESSAGE" | grep -qiE '(thumbs?\s*down|👎|-1|wrong|incorrect|bad|mistake|error|failed|broken|bug|issue|problem|lie|lies|lying|dishonest|false\s*promise|false\s*promises|hallucinat|made\s*up)'; then
  queue_feedback "negative" "$USER_MESSAGE"

  # Local-only RLHF + lessons (powers lightweight RAG at session start).
  # Best-effort: never fail the hook.
  if command -v node >/dev/null 2>&1; then
    MSG_ONE_LINE="$(echo "$USER_MESSAGE" | tr '\n' ' ' | head -c 500)"
    node "$SCRIPT_DIR/../scripts/feedback/capture-feedback.js" down "$MSG_ONE_LINE" >/dev/null 2>&1 || true
    node "$SCRIPT_DIR/../scripts/feedback/auto-lesson-creator.js" process >/dev/null 2>&1 || true
  fi
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

# Strategy question detection for truth-loop workflow
STRATEGY_KEYWORDS="make money|revenue|first dollar|waste of time|business idea|deep research|how to make this work|be honest|truth|truthful|solid plan|viability|go to market"
if echo "$USER_MESSAGE_LOWER" | grep -qiE "$STRATEGY_KEYWORDS"; then
  queue_strategy_question "$USER_MESSAGE"
fi

exit 0
