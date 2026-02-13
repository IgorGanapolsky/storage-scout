# Integration Setup Guide (CallCatcher Ops)

This document lists third-party integrations and required GitHub secrets for this repository.

## Required Secrets

Add in `Settings -> Secrets and variables -> Actions`.

| Secret | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude review workflows |
| `SONAR_TOKEN` | SonarCloud scanning |
| `SNYK_TOKEN` | Dependency vulnerability scanning |

## Optional Runtime Secrets (local preferred)
- SMTP credentials for outreach engine (`autonomy/`)
- Google Places API key for lead generation (`autonomy/tools/lead_gen_broward.py`)

These should stay in local `.env` or secure secret stores, never committed.

## SonarCloud
1. Create/import project `IgorGanapolsky/storage-scout`.
2. Set project key: `IgorGanapolsky_storage-scout`.
3. Add `SONAR_TOKEN` in GitHub secrets.

## Claude Review
1. Create API key in Anthropic console.
2. Add `ANTHROPIC_API_KEY`.
3. Verify `.github/workflows/claude-review.yml` is enabled.

## Snyk
1. Create Snyk token.
2. Add `SNYK_TOKEN`.
3. Confirm CI shows Snyk job output.

## Verification
Create a test PR and confirm:
- CI runs (`Python Quality`, `Security`, optional Sonar/Snyk)
- Claude review comment appears
- No secret scanning alerts
