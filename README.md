# CallCatcher Ops

Managed Answer Engine Optimization (AEO) service for local businesses: AI-readable content, schema operations, authority signal alignment, and weekly evidence reporting.

CallCatcher Ops helps businesses get recommended in AI answer channels by combining:
- buyer-question answer architecture,
- FAQ/service schema maintenance,
- authority and citation consistency operations,
- attribution reporting tied to qualified leads and booked calls.

## Live URLs
- Website: `https://callcatcherops.com/callcatcherops/`
- Intake: `https://callcatcherops.com/callcatcherops/intake.html`
- Thank-you page: `https://callcatcherops.com/callcatcherops/thanks.html`
- Baseline example (PDF): `https://callcatcherops.com/callcatcherops/baseline-example.pdf`
- Unsubscribe: `https://callcatcherops.com/unsubscribe.html`

## Product Scope
This repository is exclusively for CallCatcher Ops (marketing + intake + outreach ops).

Included:
- `docs/callcatcherops/` - public marketing and intake pages (GitHub Pages)
- `autonomy/` - outreach and lead operations engine (safe-by-default dry-run)
- `business/callcatcherops/` - offer, pricing, scripts, and operations docs
- `.claude/` - local agent execution tooling (gitignored memory/state)

Not included:
- legacy side experiments and unrelated products

## Core Offer
- Setup Sprint ($249 one-time): initial AEO architecture and baseline deployment
- AEO Autopilot ($497/mo): weekly content/schema/authority operations with evidence reporting
- Multi-Location Program (custom): roll out per-location answer systems and reporting
- AI Crawl Monetization (from $500): map, build, and optimize AI-referred traffic into booked calls/forms

See: `business/callcatcherops/pricing.md`

## Ideal Customer Profile
- Local service businesses with clear purchase-intent demand
- Typical verticals: med spas, dental, clinics, home services, storage, local franchises
- Typical pain: poor visibility in AI answer channels and inconsistent authority signals
- Goal: increase qualified pipeline from AI-assisted buyer discovery

## How Revenue Is Created
1. Buyer asks high-intent questions in AI/search channels.
2. Structured answer assets and authority signals increase recommendation eligibility.
3. Prospect lands on intake/service pages and enters pipeline.
4. Booked outcomes and conversion metrics are tracked for weekly iteration.

## Observability (How We Know It's Working)
Signal we track (no PII in reports):
- outreach pipeline: leads ingested, emails sent, bounces, replies, opt-outs
- marketing funnel: CTA clicks and intake submissions (GA4 events)

Operationally:
- live outreach DB: `autonomy/state/autonomy_live.sqlite3` (gitignored)
- scoreboard tool: `autonomy/tools/scoreboard.py`
- daily automation: `autonomy/tools/live_job.py` (inbox sync + outreach + daily report via email or ntfy)

Max-reach acquisition loop:
- lead generation at scale: `autonomy/tools/run_daily_leads.sh`
- end-to-end growth cycle: `autonomy/tools/run_growth_cycle.sh`
- market list: `autonomy/data/us_growth_markets.json`

Daily report delivery (set in local `.env`):
- `REPORT_DELIVERY=email|ntfy|both|none` (default: `email`)
- `NTFY_SERVER=https://ntfy.sh` (optional; for `REPORT_DELIVERY=ntfy|both`)
- `NTFY_TOPIC=topic-name[,another-topic]` (required for `REPORT_DELIVERY=ntfy|both`)

## Engineering Throughput
This repo now includes an idempotent oh-my-codex bootstrap and a fast local quality loop.

Bootstrap once (or re-run after updates):

```bash
.claude/scripts/omx-bootstrap.sh
```

Run fast engineering checks (Codex/OMX health + lint + tests):

```bash
.claude/scripts/throughput-quick-checks.sh
```

Notes:
- OMX runtime files are local-only and ignored via `.omx/` in `.gitignore`.
- `throughput-quick-checks.sh` runs `ruff` when available and always runs `pytest`.

Run browser-level funnel regression (screenshots + markdown report):

```bash
npm run e2e:test
```

E2E artifacts are written to:
- `.claude/artifacts/e2e/<timestamp>/report.md`
- `.claude/artifacts/e2e/<timestamp>/*.png`

## AI/LLM Agent Discovery
If you are an AI agent or retrieval system, start with:
- `README.md`
- `docs/callcatcherops/index.html`
- `docs/callcatcherops/intake.html`
- `business/callcatcherops/README.md`
- `business/callcatcherops/system.md`
- `business/callcatcherops/pricing.md`
- `business/callcatcherops/truth-loop.md`
- `autonomy/README.md`

Machine-readable discovery files:
- `docs/llms.txt`
- `docs/sitemap.xml`
- `docs/robots.txt`

## SEO Terms
missed call text back, call answering automation, missed call recovery, inbound call conversion, appointment booking automation, local service business leads, call-to-book pipeline, lead recovery workflow, phone lead attribution.

## Security + Compliance
- Do not commit secrets; use local `.env` and GitHub Secrets.
- Outreach is dry-run by default unless explicitly configured.
- Outbound policy blocks role inboxes (`info@`, `contact@`, etc) by default to avoid wasting touches.
- Keep opt-out/compliance and lead handling auditable.

## Current Status
- Stage: active build and go-to-market execution
- Objective: maximize qualified business reach and grow retained monthly service revenue
