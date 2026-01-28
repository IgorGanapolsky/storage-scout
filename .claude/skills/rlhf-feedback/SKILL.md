---
name: rlhf-feedback
description: Capture and learn from human feedback (thumbs up/down) to improve future responses
version: 1.0.0
author: Storage Scout
tags:
  - feedback
  - learning
  - memory
  - rlhf
triggers:
  - thumbs up
  - thumbs down
  - good job
  - wrong
  - mistake
---

# RLHF Feedback Skill

## Purpose
Capture and learn from human feedback (thumbs up/down) to improve future responses.

## Trigger Conditions
- User gives thumbs up: 👍, "+1", "good job", "great", "excellent", "amazing", "perfect"
- User gives thumbs down: 👎, "-1", "wrong", "incorrect", "mistake", "error", "bug"

## Domain Tags (Storage Scout)
- `spread` - Spread calculation and formula
- `flutter` - Flutter/Dart mobile app
- `github` - Git operations, PRs, branches
- `api` - HTTP requests, GitHub API
- `testing` - Unit tests, TDD
- `csv` - Data storage and export
- `notification` - ntfy.sh push alerts
- `validation` - Input validation
- `security` - Tokens, credentials, env vars
- `ci` - GitHub Actions, CI/CD

## Action Tags
- `implementation` - Adding new features
- `fix` - Bug fixes
- `refactor` - Code improvements
- `testing` - Test coverage
- `documentation` - Docs and comments
- `configuration` - Setup and config
- `git-operations` - Commits, PRs, merges

## Outcome Categories

### Positive
- `quick-success` - Fast, efficient solution
- `deep-success` - Thorough, comprehensive
- `creative-success` - Elegant, innovative
- `standard-success` - Meets expectations

### Negative
- `hallucination` - Made up facts (CRITICAL)
- `factual-error` - Wrong information (HIGH)
- `insufficient-depth` - Incomplete solution (MEDIUM)
- `inefficiency` - Slow or wasteful (LOW)
- `general-error` - Other errors (MEDIUM)

## Files
- `capture-feedback.js` - Records feedback with context
- `auto-lesson-creator.js` - Generates lessons from mistakes
- `semantic-memory.py` - LanceDB vector search + BM25 hybrid
- `user-prompt-submit.sh` - Hook for automatic detection
- `session-start.sh` - Injects lessons at session start

## LanceDB Semantic Memory

### Setup
```bash
pip install -r .claude/scripts/feedback/requirements.txt
python .claude/scripts/feedback/semantic-memory.py --index
```

### Features
- **Hybrid Search**: BM25 (30%) + Vector similarity (70%)
- **LRU Cache**: Fast repeated queries
- **Similarity Threshold**: Only returns relevant results (>0.7)
- **Query Metrics**: Tracks latency and hit rates

### Commands
```bash
python .claude/scripts/feedback/semantic-memory.py --index    # Build index
python .claude/scripts/feedback/semantic-memory.py --query "spread calculation"
python .claude/scripts/feedback/semantic-memory.py --context  # Session context
python .claude/scripts/feedback/semantic-memory.py --status   # Index status
python .claude/scripts/feedback/semantic-memory.py --metrics  # Query metrics
```

## Usage

### Manual Capture
```bash
node .claude/scripts/feedback/capture-feedback.js up "Great TDD implementation"
node .claude/scripts/feedback/capture-feedback.js down "Forgot edge case in validation"
node .claude/scripts/feedback/capture-feedback.js stats
```

### Automatic (via hooks)
Feedback is automatically captured when user messages contain trigger words.

### View Lessons
```bash
cat .claude/memory/lessons-learned.md
```

## Learning Loop

```
User Feedback → capture-feedback.js → feedback-log.jsonl
                        ↓
              (if negative)
                        ↓
              auto-lesson-creator.js → lessons/*.json
                        ↓
              lessons-learned.md
                        ↓
              semantic-memory.py --index (LanceDB)
                        ↓
              session-start.sh → semantic-memory.py --context
                        ↓
              Claude gets relevant lessons via hybrid search
                        ↓
              Claude avoids repeating mistakes
```

## Architecture (2026 Best Practices)

```
┌─────────────────────────────────────────────────────────┐
│  HYBRID SEARCH ENGINE                                   │
│  ┌────────────────┐  ┌────────────────┐                │
│  │ BM25 (Keywords)│ + │ Vector (Semantic)│ = Fusion    │
│  └────────────────┘  └────────────────┘                │
└─────────────────────────────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              │  LanceDB Storage    │
              │  + Similarity Filter │
              │  + LRU Cache        │
              └─────────────────────┘
```
