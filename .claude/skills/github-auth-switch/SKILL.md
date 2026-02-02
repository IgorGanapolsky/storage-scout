# GitHub Auth Switch Skill

Switch GitHub CLI authentication between personal and work accounts autonomously.

## Trigger
- User mentions GitHub auth issues
- PR operations fail with "Enterprise Managed User" error
- Need to use personal GitHub account (IgorGanapolsky)
- gh CLI using wrong account

## Problem
The `GITHUB_TOKEN` environment variable overrides gh CLI authentication, causing it to use the wrong account (e.g., EMU work account instead of personal).

## Solution

### 1. Check Current Auth Status
```bash
gh auth status
```

Look for:
- Which account is "Active account: true"
- Whether GITHUB_TOKEN is overriding

### 2. Switch to Personal Account
```bash
unset GITHUB_TOKEN && gh auth switch --user IgorGanapolsky
```

### 3. Verify Switch Worked
```bash
unset GITHUB_TOKEN && gh auth status
```

Confirm IgorGanapolsky shows "Active account: true"

### 4. Run gh Commands with Unset Token
Always prefix gh commands with `unset GITHUB_TOKEN &&` to prevent EMU override:
```bash
unset GITHUB_TOKEN && gh pr merge 41 --repo IgorGanapolsky/storage-scout --squash
```

## Key Accounts
- **Personal**: `IgorGanapolsky` - Use for personal repos (storage-scout, igor)
- **Work EMU**: `ganapolsky-i_subway` - Subway corporate repos only

## Common Errors

### "Unauthorized: As an Enterprise Managed User"
The GITHUB_TOKEN env var is set to an EMU token. Fix:
```bash
unset GITHUB_TOKEN && gh auth switch --user IgorGanapolsky
```

### "HTTP 403: Resource not accessible"
Wrong account for the repo. Check which account owns the repo and switch accordingly.

## Prevention
Add to shell profile (~/.zshrc):
```bash
# Alias for personal GitHub operations
alias ghp='unset GITHUB_TOKEN && gh'
```

Then use `ghp pr merge` instead of `gh pr merge` for personal repos.
