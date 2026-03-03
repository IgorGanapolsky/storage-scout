# AEO Autopilot - Claude Configuration

## Project Overview
AEO Autopilot is a done-for-you AI-SEO (AEO) service. This repo contains the public funnel, autonomous operations scripts, and GTM playbooks.

## Architecture
- `docs/ai-seo/` - Public website and onboarding funnel
- `autonomy/` - Autonomous execution and reporting engine
- `business/ai-seo/` - Offer, pricing, sales playbooks
- `docs/` - Redirect/discovery files

## Operating Rules
- Execute autonomously; do not hand off manual steps when tooling can do it.
- Use a dedicated git worktree for all implementation tasks.
- Never commit secrets or PII.
- Keep claims evidence-based; avoid guaranteed ranking/revenue language.

## Core Commands
```bash
python3 autonomy/tools/live_job.py --config autonomy/state/config.ai-seo.live.json
python3 autonomy/tools/scoreboard.py
npm run e2e:test
```

## PR Management & Hygiene Directive
- Operate autonomously for PR triage, merge, and repo hygiene with no manual handoff unless action is irreversible or credentials are missing.
- At session start: read `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`, query local TruthGuard, inspect open PRs, branches, and CI.
- For open PRs: report readiness, blockers, and merge only when checks/reviews are green.
- For branches/worktrees: identify orphan branches, delete only safe stale/merged ones, and report before/after counts.
- Verify CI on `main` (and `develop` when present) after merges.
- Run an operational dry run before final completion claims.
- Keep all claims evidence-backed (SHAs, run URLs, counts, command results).
- Do not store secrets in repository files.
