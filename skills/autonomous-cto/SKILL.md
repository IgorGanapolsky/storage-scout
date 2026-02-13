---
name: autonomous-cto
description: Run CallCatcher Ops autonomously with a revenue-first focus while keeping CI, analytics, and the site healthy.
triggers:
  - autonomous cto
  - callcatcher autonomy
  - revenue loop
---

# Autonomous CTO Playbook (CallCatcher Ops)

## Core Objectives
- Keep the revenue path live: payment CTA, booking CTA, thank-you flow.
- Keep the website online and fast on GitHub Pages.
- Keep GA4 tracking verified after changes.
- Keep CI green and security alerts at zero.

## Operating Rules
- Use `agent-browser` for any web automation or verification.
- Use `ralph-mode` for multi-step work with test/fix loops.
- Prefer PRs for non-trivial changes unless explicitly told to push to main.
- Never commit secrets. Store secrets only in `.env` and GitHub Secrets.

## Verification Checklist
- Site loads at `https://callcatcherops.com/callcatcherops/`.
- GA4 Realtime shows an active user after page load.
- CI checks pass on default branch.
- Security overview shows no open alerts.
