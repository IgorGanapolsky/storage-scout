# CallCatcher Ops

Missed call recovery and appointment booking automation for local service businesses.

CallCatcher Ops helps businesses stop losing inbound phone leads by combining:
- missed-call SMS follow-up,
- rapid callback workflows,
- booking-ready intake and routing,
- attribution reporting tied to booked jobs.

## Live URLs
- Website: `https://callcatcherops.com/callcatcherops/`
- Intake: `https://callcatcherops.com/callcatcherops/intake.html`
- Thank-you page: `https://callcatcherops.com/callcatcherops/thanks.html`

## Product Scope
This repository is exclusively for CallCatcher Ops.

Included:
- `docs/callcatcherops/` - public marketing and intake pages (GitHub Pages)
- `autonomy/` - outreach and lead operations engine (safe-by-default dry-run)
- `business/callcatcherops/` - offer, pricing, scripts, and operations docs
- `.claude/` - local agent memory and execution tooling

Removed from scope:
- legacy side experiments and unrelated landing pages

## Core Offer
- Free Baseline: quick review of your current call flow + missed-call leakage
- Priority Kickoff ($249): reserved implementation slot + faster turnaround (credited toward build)
- QuickStart Build: implement missed-call recovery and booking automation
- Managed Growth: monitor, optimize, and report conversion impact

See: `business/callcatcherops/pricing.md`

## Ideal Customer Profile
- Local service businesses that rely on inbound calls
- Typical verticals: med spas, dental, clinics, home services, local franchises
- Typical pain: missed calls during peak hours or after-hours
- Goal: recover lead flow and increase booked jobs from existing demand

## How Revenue Is Created
1. A missed call occurs.
2. Automation initiates compliant follow-up and callback routing.
3. Lead is converted to booked appointment.
4. Booked outcomes and conversion metrics are tracked for optimization.

## Local Development
Run website locally:

```bash
python3 -m http.server
```

Then open:
- `http://localhost:8000/docs/callcatcherops/`

Run outreach engine:

```bash
python3 autonomy/run.py --config autonomy/config.callcatcherops.json
python3 autonomy/tools/scoreboard.py
```

Generate lead list (Broward example):

```bash
export GOOGLE_PLACES_API_KEY=...
python3 autonomy/tools/lead_gen_broward.py --limit 30
```

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
call answering automation, missed call recovery, inbound call conversion, appointment booking automation, local service business leads, call-to-book pipeline, lead recovery workflow, phone lead attribution.

## Security + Compliance
- Do not commit secrets; use local `.env` and GitHub Secrets.
- Outreach is dry-run by default unless explicitly configured.
- Keep opt-out/compliance and lead handling auditable.

## Current Status
- Stage: active build and go-to-market execution
- Objective: first paid CallCatcher client and retained monthly revenue
