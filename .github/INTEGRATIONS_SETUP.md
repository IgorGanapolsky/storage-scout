# Integration Setup Guide

This document lists all third-party integrations and the secrets required.

## Required Secrets

Add these in **Settings → Secrets and variables → Actions**:

| Secret | Service | How to Get |
|--------|---------|------------|
| `ANTHROPIC_API_KEY` | Claude AI Review | https://console.anthropic.com/settings/keys |
| `SONAR_TOKEN` | SonarCloud | https://sonarcloud.io/account/security |
| `SENTRY_AUTH_TOKEN` | Sentry | https://sentry.io/settings/account/api/auth-tokens/ |
| `SENTRY_ORG` | Sentry | Your Sentry organization slug |
| `CODECOV_TOKEN` | Codecov | https://app.codecov.io/gh/IgorGanapolsky/storage-scout/settings |

---

## 1. SonarCloud Setup

1. Go to https://sonarcloud.io/projects/create
2. Import `IgorGanapolsky/storage-scout` from GitHub
3. Copy the token from setup wizard
4. Add as `SONAR_TOKEN` secret
5. Project will auto-analyze on next push

**Dashboard:** https://sonarcloud.io/project/overview?id=IgorGanapolsky_storage-scout

---

## 2. Sentry Setup

1. Go to https://sentry.io/organizations/new/
2. Create organization (or use existing)
3. Create project: **Flutter** → name: `storage-scout`
4. Get auth token: Settings → Auth Tokens → Create New Token
   - Scopes: `project:releases`, `org:read`
5. Add secrets:
   - `SENTRY_AUTH_TOKEN`: Your auth token
   - `SENTRY_ORG`: Your organization slug

**Note:** Sentry releases only trigger on pushes to `main` branch.

---

## 3. Claude Code Review

1. Go to https://console.anthropic.com/settings/keys
2. Create new API key
3. Add as `ANTHROPIC_API_KEY` secret

**Features:**
- Automatic PR review on open/sync
- `@claude` mention for on-demand assistance
- Custom prompts for Storage Scout context

---

## 4. GitHub Copilot

See `.github/COPILOT_SETUP.md` for detailed instructions.

**Quick setup:**
1. Settings → Code security and analysis → Enable Copilot features
2. Settings → Rules → Rulesets → Enable Copilot code review

---

## 5. Codecov (Optional)

1. Go to https://app.codecov.io/gh/IgorGanapolsky/storage-scout
2. Get upload token from settings
3. Add as `CODECOV_TOKEN` secret

---

## Verification

After setup, create a test PR to verify all integrations:

```bash
git checkout -b test/integrations
echo "# Test" >> TEST.md
git add TEST.md && git commit -m "Test integrations"
git push -u origin test/integrations
gh pr create --title "Test integrations" --body "Testing CI/CD integrations"
```

Expected PR comments:
- Claude AI code review
- Copilot code review (if enabled in rulesets)
- CI status summary with SonarCloud results
