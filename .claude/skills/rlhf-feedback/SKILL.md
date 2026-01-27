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
- `user-prompt-submit.sh` - Hook for automatic detection
- `session-start.sh` - Injects lessons at session start

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
              session-start.sh (inject at start)
                        ↓
              Claude avoids repeating mistakes
```
