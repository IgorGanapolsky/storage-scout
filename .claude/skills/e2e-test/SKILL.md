---
name: e2e-test
description: Comprehensive end-to-end browser validation for CallCatcher Ops funnel pages with screenshots and a markdown report.
version: 1.0.0
author: Storage Scout
tags:
  - e2e
  - regression
  - qa
  - browser-automation
  - agent-browser
triggers:
  - /e2e test
  - run e2e
  - end-to-end test
  - validate funnel
---

# E2E Test Skill

## Purpose
Run a full browser-level regression pass for the public CallCatcher Ops funnel and produce verifiable artifacts.

## What This Skill Validates
- Local docs site can be served and navigated.
- Core conversion paths still work:
  - Landing -> Intake
  - Landing -> Workflow Subscription
  - Landing -> AI Crawl Monetization
  - AI Crawl Monetization -> Assessment
  - Workflow Subscription -> AI Crawl Monetization
  - Thanks -> Workflow Subscription
- Screenshots are captured for each journey.
- A structured markdown report is generated.

## Prerequisites
- macOS/Linux shell (Windows via WSL recommended).
- `python3`, `npm`/`npx`, and `agent-browser` (via `npx` or global install).
- Browser binaries installed (`agent-browser install` handles this).

## Command
Run from repo root:

```bash
./.claude/scripts/e2e/e2e-test.sh
```

Optional:

```bash
E2E_PORT=4173 E2E_BASE_URL=http://127.0.0.1:4173 ./.claude/scripts/e2e/e2e-test.sh
```

## Outputs
- Artifacts root: `.claude/artifacts/e2e/<timestamp>/`
- Per-journey screenshots: `NN-*.png`
- Server log: `server.log`
- Summary report: `report.md`
- Machine-readable status: `summary.txt`

## Repo-Specific Notes
- This repo is a static funnel in `docs/`; the runner starts a local `python3 -m http.server`.
- DB-level validation is optional for this project and intentionally excluded from the default pass.

