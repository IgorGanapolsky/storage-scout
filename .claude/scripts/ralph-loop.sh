#!/bin/bash
#
# Ralph Mode - Autonomous Infinite Loop
# 2026 Best Practices Implementation
#
# Usage:
#   ./ralph-loop.sh start "Task description" [issue-number]
#   ./ralph-loop.sh status
#   ./ralph-loop.sh stop
#
# Features:
#   - Infinite bash loop: code, test, fix, repeat
#   - Checkpoint commits after each successful fix
#   - Audit trail logging
#   - Superior intelligence review on completion
#   - Auto-PR creation with squash merge

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RALPH_DIR="$PROJECT_ROOT/.claude/memory/ralph"
STATE_FILE="$RALPH_DIR/current-session.json"
LOG_FILE="$RALPH_DIR/audit-trail.jsonl"
MAX_ITERATIONS=${RALPH_MAX_ITERATIONS:-50}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

mkdir -p "$RALPH_DIR"

log_audit() {
    local event="$1"
    local data="$2"
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "{\"timestamp\":\"$timestamp\",\"event\":\"$event\",\"data\":$data}" >> "$LOG_FILE"
}

show_banner() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    🤖 RALPH MODE 2026                        ║"
    echo "║           Autonomous Infinite Loop Agent                     ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

default_test_cmd() {
    # Prefer the autonomy Python test suite when present; otherwise fall back to repo tests.
    if [ -d "$PROJECT_ROOT/autonomy/tests" ]; then
        echo "python3 -m pytest -q autonomy/tests --maxfail=1"
        return
    fi
    if [ -d "$PROJECT_ROOT/flutter_scout_app" ]; then
        echo "cd flutter_scout_app && flutter test"
        return
    fi
    echo "python3 -m pytest -q --maxfail=1"
}

start_session() {
    local description="$1"
    local issue_number="${2:-}"

    show_banner

    if [ -f "$STATE_FILE" ]; then
        echo -e "${YELLOW}Warning: Session already in progress. Use 'ralph-loop.sh stop' first.${NC}"
        cat "$STATE_FILE" | jq .
        return 1
    fi

    # Create feature branch
    local branch_name="ralph/$(date +%Y%m%d-%H%M%S)"
    if [ -n "$issue_number" ]; then
        branch_name="ralph/issue-$issue_number-$(date +%s)"
    fi

    git checkout -b "$branch_name" 2>/dev/null || git checkout "$branch_name"

    # Initialize session state
    cat > "$STATE_FILE" << EOF
{
    "session_id": "$(uuidgen | tr '[:upper:]' '[:lower:]' || date +%s)",
    "started_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "description": "$description",
    "issue_number": "$issue_number",
    "branch": "$branch_name",
    "iteration": 0,
    "status": "running",
    "test_passes": 0,
    "test_failures": 0,
    "commits": []
}
EOF

    log_audit "session_started" "{\"description\":\"$description\",\"branch\":\"$branch_name\"}"

    echo -e "${GREEN}Ralph Mode session started${NC}"
    echo "  Branch: $branch_name"
    echo "  Task: $description"
    echo "  Max iterations: $MAX_ITERATIONS"
    echo ""
    echo -e "${YELLOW}Instructions for Claude:${NC}"
    echo ""
    echo "You are now in RALPH MODE. Follow this loop:"
    echo ""
    echo "  1. IMPLEMENT the task described above"
    echo "  2. RUN tests: ${RALPH_TEST_CMD:-$(default_test_cmd)}"
    echo "  3. If tests PASS:"
     echo "     - Commit with: git add -A && git commit -m 'Ralph: <what you did>'"
    echo "     - Continue to next subtask or finish"
    echo "  4. If tests FAIL:"
    echo "     - Analyze the error"
    echo "     - Fix the code"
    echo "     - Go back to step 2"
    echo ""
    echo "  LOOP until all tests pass or you've tried $MAX_ITERATIONS times."
    echo ""
    echo "  When complete, run: .claude/scripts/ralph-loop.sh finish"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

record_iteration() {
    local result="$1"  # "pass" or "fail"
    local details="$2"

    if [ ! -f "$STATE_FILE" ]; then
        echo "No active session"
        return 1
    fi

    local iteration=$(jq -r '.iteration' "$STATE_FILE")
    iteration=$((iteration + 1))

    if [ "$result" == "pass" ]; then
        jq ".iteration = $iteration | .test_passes += 1" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
    else
        jq ".iteration = $iteration | .test_failures += 1" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
    fi

    log_audit "iteration" "{\"number\":$iteration,\"result\":\"$result\",\"details\":\"$details\"}"

    echo -e "${BLUE}Iteration $iteration: $result${NC}"
}

show_status() {
    if [ ! -f "$STATE_FILE" ]; then
        echo "No active Ralph Mode session"
        return 0
    fi

    show_banner
    echo -e "${GREEN}Current Session:${NC}"
    cat "$STATE_FILE" | jq .

    echo ""
    echo -e "${BLUE}Recent Activity:${NC}"
    tail -5 "$LOG_FILE" 2>/dev/null | jq -r '"\(.timestamp) | \(.event): \(.data)"' || echo "No activity logged"
}

finish_session() {
    if [ ! -f "$STATE_FILE" ]; then
        echo "No active session to finish"
        return 1
    fi

    show_banner

    local branch=$(jq -r '.branch' "$STATE_FILE")
    local description=$(jq -r '.description' "$STATE_FILE")
    local issue=$(jq -r '.issue_number' "$STATE_FILE")
    local iterations=$(jq -r '.iteration' "$STATE_FILE")
    local passes=$(jq -r '.test_passes' "$STATE_FILE")
    local failures=$(jq -r '.test_failures' "$STATE_FILE")

    echo -e "${GREEN}Finishing Ralph Mode session...${NC}"
    echo "  Iterations: $iterations"
    echo "  Test passes: $passes"
    echo "  Test failures: $failures"

    # Update state
    jq '.status = "completed" | .completed_at = "'"$(date -u +"%Y-%m-%dT%H:%M:%SZ")"'"' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"

    # Push branch
    git push -u origin "$branch" 2>/dev/null || true

    # Create PR
    local pr_body="## Ralph Mode Autonomous Implementation

**Task:** $description
$([ -n "$issue" ] && [ "$issue" != "null" ] && echo "**Closes:** #$issue")

### Metrics
- Iterations: $iterations
- Test passes: $passes
- Test failures: $failures

---
🤖 Generated autonomously by Ralph Mode

**Requires superior intelligence review before merge.**"

    local pr_url=$(gh pr create \
        --title "Ralph: $description" \
        --body "$pr_body" \
        --base develop \
        --head "$branch" \
        --label "ralph-mode" 2>/dev/null || echo "")

    if [ -n "$pr_url" ]; then
        echo -e "${GREEN}PR created: $pr_url${NC}"
        log_audit "pr_created" "{\"url\":\"$pr_url\"}"

        # Enable auto-merge
        gh pr merge "$pr_url" --auto --squash 2>/dev/null || true
    fi

    log_audit "session_completed" "{\"iterations\":$iterations,\"passes\":$passes,\"failures\":$failures}"

    # Archive session
    mv "$STATE_FILE" "$RALPH_DIR/completed-$(date +%Y%m%d-%H%M%S).json"

    echo ""
    echo -e "${GREEN}Ralph Mode session complete!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Superior intelligence will review the PR"
    echo "  2. If approved, it will auto-merge"
    echo "  3. Check: gh pr view"
}

stop_session() {
    if [ ! -f "$STATE_FILE" ]; then
        echo "No active session"
        return 0
    fi

    jq '.status = "stopped"' "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
    log_audit "session_stopped" "{}"

    mv "$STATE_FILE" "$RALPH_DIR/stopped-$(date +%Y%m%d-%H%M%S).json"

    echo -e "${YELLOW}Ralph Mode session stopped${NC}"
}

# Main command dispatch
case "${1:-status}" in
    start)
        if [ -z "$2" ]; then
            echo "Usage: ralph-loop.sh start \"Task description\" [issue-number]"
            exit 1
        fi
        start_session "$2" "${3:-}"
        ;;
    status)
        show_status
        ;;
    finish)
        finish_session
        ;;
    stop)
        stop_session
        ;;
    pass)
        record_iteration "pass" "${2:-Tests passed}"
        ;;
    fail)
        record_iteration "fail" "${2:-Tests failed}"
        ;;
    *)
        echo "Usage: ralph-loop.sh {start|status|finish|stop|pass|fail}"
        echo ""
        echo "Commands:"
        echo "  start \"desc\" [issue]  - Start new Ralph Mode session"
        echo "  status                 - Show current session status"
        echo "  finish                 - Complete session and create PR"
        echo "  stop                   - Abort session without PR"
        echo "  pass [msg]             - Record test pass iteration"
        echo "  fail [msg]             - Record test fail iteration"
        exit 1
        ;;
esac
