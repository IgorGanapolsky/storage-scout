# CallCatcher Ops — Missed-Call Recovery + Appointment Booking Automation

CallCatcher Ops helps local service businesses recover missed calls and turn them into booked jobs using SMS + call-back automation. This repo contains the marketing site, outbound tooling, and operations playbooks needed to acquire and onboard customers quickly.

## What This Repo Is For
- Generate and convert leads for a $249 recovery audit offer.
- Publish a fast, SEO-friendly marketing site via GitHub Pages.
- Run compliant outbound with throttling, logging, and replayable lead lists.
- Keep deployment, DNS, email, and analytics documented in one place.

## Repo Map
- `docs/callcatcherops/` — Marketing site (GitHub Pages)
- `autonomy/` — Outreach engine (CSV leads + SMTP, dry-run default)
- `business/callcatcherops/` — Pricing, outreach scripts, deployment notes
- `docs/` — Other public landing pages
- `tools_rental/` — Optional experiments

## How It Works
- Capture leads with a short intake form and immediate payment CTA.
- Route booked calls through Calendly.
- Deliver a recovery audit and convert to implementation.

## AI/LLM Agent Notes
- Start with `business/callcatcherops/README.md` for the go-to-market overview.
- The marketing site lives in `docs/callcatcherops/`.
- The outbound engine lives in `autonomy/`.

## Keywords
missed-call recovery, appointment booking, local service businesses, SMS automation, outbound sales, lead recovery, call tracking, revenue recovery, AI agents, LLM ops

## Quick Start
1. Edit the site: `docs/callcatcherops/index.html`
2. Deploy via GitHub Pages (custom domain handled in `business/callcatcherops/DEPLOYMENT.md`)
3. Copy `autonomy/config.example.json` to a new config
4. Run `python3 autonomy/run.py` (requires SMTP creds to go live)
