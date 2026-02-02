# Auto CodeQL Fix Skill

Automatically monitor and fix CodeQL security alerts on every session start.

## Trigger
- **Auto on session start** - Check for open CodeQL alerts
- `/codeql-fix` - Manual trigger

## Autonomous Operation

This skill runs automatically WITHOUT user prompts. On every session:

1. **Check for alerts**: `gh api repos/{owner}/{repo}/code-scanning/alerts --jq '.[] | select(.state == "open")'`
2. **If alerts exist**: Create fix branch, resolve alerts, push PR
3. **If no alerts**: Silent - no output needed

## Alert Priority

| Severity | Action |
|----------|--------|
| `critical`, `high` | Fix immediately, urgent PR |
| `medium` | Fix in batch PR |
| `low`, `note` | Fix in batch PR (unused imports, etc.) |

## Common Fixes

### py/unused-import
Remove the unused import line.

### py/incomplete-url-substring-sanitization
Use proper URL validation:
```python
from urllib.parse import urlparse
parsed = urlparse(url)
if parsed.netloc not in ALLOWED_DOMAINS:
    raise ValueError("Invalid URL")
```

### py/catch-base-exception
Replace `except:` or `except BaseException:` with specific exceptions:
```python
except (ValueError, TypeError, KeyError) as e:
```

### js/unused-variable
Remove the unused variable declaration.

## Workflow

```bash
# 1. Fetch alerts
unset GITHUB_TOKEN && gh api repos/IgorGanapolsky/storage-scout/code-scanning/alerts \
  --jq '.[] | select(.state == "open") | {number, rule: .rule.id, file: .most_recent_instance.location.path, line: .most_recent_instance.location.start_line}'

# 2. Clone and branch
git clone <repo> /tmp/codeql-fix
git checkout -b ralph/fix-codeql-$(date +%Y%m%d)

# 3. Fix each alert (based on rule type)

# 4. Commit, push, PR with auto-merge
gh pr create --title "fix: Resolve CodeQL alerts" --body "..."
gh pr merge --auto --squash
```

## GitHub Actions Integration

Add to `.github/workflows/codeql-autofix.yml`:
```yaml
name: CodeQL Auto-Fix
on:
  schedule:
    - cron: '0 6 * * *'  # Daily at 6am
  workflow_dispatch:

jobs:
  autofix:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check CodeQL alerts
        run: |
          ALERTS=$(gh api repos/${{ github.repository }}/code-scanning/alerts --jq '[.[] | select(.state == "open")] | length')
          if [ "$ALERTS" -gt 0 ]; then
            echo "Found $ALERTS open alerts - triggering Claude fix"
            # Trigger Claude Code via webhook or issue
          fi
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Session Start Hook

Add to `.claude/hooks/session-start.sh`:
```bash
# Auto-check CodeQL alerts
ALERTS=$(unset GITHUB_TOKEN && gh api repos/IgorGanapolsky/storage-scout/code-scanning/alerts --jq '[.[] | select(.state == "open")] | length' 2>/dev/null || echo "0")
if [ "$ALERTS" -gt 0 ]; then
  echo "WARNING: $ALERTS open CodeQL security alerts. Run /codeql-fix to resolve."
fi
```

## Prevention

To prevent alerts from accumulating:

1. **Pre-commit hook**: Run `ruff check --select F401` (unused imports)
2. **CI gate**: Block PRs with new CodeQL alerts
3. **Session start**: Auto-check and fix

## Metrics

Track in `.claude/memory/codeql-stats.json`:
```json
{
  "total_fixed": 42,
  "by_rule": {
    "py/unused-import": 25,
    "py/catch-base-exception": 10,
    "py/incomplete-url-substring-sanitization": 7
  },
  "last_scan": "2026-02-02T08:30:00Z"
}
```
