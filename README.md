# AEO Autopilot

Autonomous AI-SEO operations for local and service businesses.

AEO Autopilot helps businesses get recommended in AI answer channels by running:
- buyer-intent answer architecture,
- schema deployment and maintenance,
- authority/citation consistency operations,
- weekly reporting tied to qualified leads.

## Live URLs
- Website: `https://aiseoautopilot.com/ai-seo/`
- Intake: `https://aiseoautopilot.com/ai-seo/intake.html`
- Thank-you page: `https://aiseoautopilot.com/ai-seo/thanks.html`
- Service page: `https://aiseoautopilot.com/ai-seo/service.html`
- FAQ: `https://aiseoautopilot.com/ai-seo/aeo-faq.html`
- Unsubscribe: `https://aiseoautopilot.com/unsubscribe.html`

## Scope
This repository is exclusively for AEO Autopilot (site + intake + autonomous growth operations).

Included:
- `docs/ai-seo/` - public website funnel
- `autonomy/` - autonomous execution engine
- `business/ai-seo/` - offer, pricing, GTM playbooks

## Core Offer
- Setup Sprint ($500 one-time): baseline + implementation plan
- Build Sprint ($1,800 one-time): execute top-impact technical/content fixes
- AEO Autopilot ($650/mo): weekly optimization and evidence reporting

See: `business/ai-seo/pricing.md`

## North Star
- First metric: `paid_aeo_clients_count`
- Business objective: grow retained monthly AEO revenue through fully managed execution

## Observability
- Funnel: CTA clicks + intake submissions
- Pipeline: leads, replies, qualified opportunities
- Revenue: paid onboardings and active retainers

Operational artifacts:
- `autonomy/state/autonomy_live.sqlite3` (gitignored)
- `autonomy/tools/scoreboard.py`
- `autonomy/tools/live_job.py`

## Automation
Primary autonomous loop:
```bash
python3 autonomy/tools/live_job.py --config autonomy/state/config.ai-seo.live.json
```

Daily lead generation loop:
```bash
bash autonomy/tools/run_daily_leads.sh
```

## Discovery Files
- `docs/llms.txt`
- `docs/sitemap.xml`
- `docs/robots.txt`

## Security
- No secrets in git.
- Local secrets in `.env`, remote secrets in GitHub Secrets.
