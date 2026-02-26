# Autonomous Outreach Engine (Frontier-Ready)

This is a minimal, production-shaped automation engine that mirrors Frontier-style architecture:
- shared business context
- explicit agent identities + permissions
- auditable action ledger
- evaluation hooks

It runs in **dry-run** by default and becomes live when credentials are provided.

## What It Does
- Ingests leads from CSV
- Scores and dedupes
- Generates compliant outreach messages
- Sends via SMTP (or logs in dry-run)
- Records every action in an audit trail

## Files
- `autonomy/config.example.json` - configuration template
- `autonomy/config.callcatcherops.json` - CallCatcher Ops config (dry-run default)
- `autonomy/data/leads_callcatcherops.csv` - sample lead list
- `autonomy/state/leads_callcatcherops_real.csv` - real lead list (gitignored; do not commit)
- `autonomy/run.py` - entrypoint
- `autonomy/engine.py` - orchestration logic
- `autonomy/context_store.py` - SQLite context store
- `autonomy/providers.py` - lead + email providers
- `autonomy/agents.py` - scoring + message generation
- `autonomy/tools/lead_gen_broward.py` - Google Places lead generator (Broward County)
- `autonomy/tools/scoreboard.py` - local outreach scoreboard (no PII)
- `autonomy/tools/opt_out.py` - record opt-outs into sqlite
- `autonomy/tools/fastmail_inbox_sync.py` - mark bounces/replies from inbox signals (no PII output)
- `autonomy/tools/twilio_interest_nudge.py` - nudge inbound "interested" SMS leads toward booking/kickoff (fully automated)
- `autonomy/tools/twilio_tollfree_watchdog.py` - monitor + auto-remediate Twilio toll-free verification status
- `autonomy/tools/live_job.py` - live daily job: inbox sync + outreach + report delivery (email or ntfy)
- `autonomy/tools/install_launchd_daily.py` - install macOS LaunchAgent for daily automation
- `autonomy/tools/install_launchd_tollfree_watchdog.py` - install hourly macOS LaunchAgent for toll-free verification monitoring

## Notes
- No secrets are committed.
- All actions are written to a JSONL audit log.
- This is intentionally minimal and extensible.

## Deliverability Policy (Default)
Cold outreach fails fast when you send to role inboxes (`info@`, `contact@`, etc). By default, the engine:
- Blocks common role inbox local-parts (configurable)
- Only emails leads whose `email_method` is in `["direct","scrape"]` (configurable)
- Pauses outreach when bounce rate spikes over a window (`bounce_pause`)

Configure in `agents.outreach`:
- `allowed_email_methods` (list or comma string)
- `blocked_local_parts` (list or comma string)
- `bounce_pause` (`enabled`, `window_days`, `threshold`, `min_emailed`)

Live-job deliverability gate controls (in `.env`):
- `DELIVERABILITY_GATE_ENABLED=1`
- `DELIVERABILITY_WINDOW_DAYS=7` (separate from scoreboard window)
- `DELIVERABILITY_MIN_EMAILS=10` (minimum sample size before blocking)
- `DELIVERABILITY_MAX_BOUNCE_RATE=0.05`

In your lead CSV, you can optionally include `email_method` (e.g. `apollo`, `linkedin`, `direct`, `scrape`). If omitted, it's inferred from `notes` and the email local-part.

## Fastmail Safety Brake
If you point SMTP at Fastmail (`smtp_host` ends with `fastmail.com`), outbound outreach is blocked by default to reduce account risk.

Override (not recommended) by setting:
- `ALLOW_FASTMAIL_OUTREACH=1`

## Auto Calls (Twilio, Optional)
The daily job can optionally place outbound calls via Twilio and log outcomes into SQLite (so the scoreboard/report reflects execution).

This is **disabled by default** and requires paid Twilio credentials in local `.env` (gitignored):
- `AUTO_CALLS_ENABLED=1`
- `TWILIO_ACCOUNT_SID=...`
- `TWILIO_AUTH_TOKEN=...`
- `TWILIO_FROM_NUMBER=+1...` (E.164)

Optional tuning:
- `AUTO_CALLS_MAX_PER_RUN=10`
- `AUTO_CALLS_COOLDOWN_DAYS=7`
- `AUTO_CALLS_START_HOUR_LOCAL=9`
- `AUTO_CALLS_END_HOUR_LOCAL=17`
- `TWILIO_INBOX_SYNC_ENABLED=1` (default on in live job)
- `AUTO_SMS_INBOUND_REPLY_ENABLED=1` (auto-reply to inbound interested replies)
- `AUTO_INTEREST_NUDGE_ENABLED=1` (default on; nudges interested inbound leads that have not booked)
- `AUTO_INTEREST_NUDGE_MAX_PER_RUN=6`
- `AUTO_INTEREST_NUDGE_MIN_AGE_MINUTES=120`
- `AUTO_INTEREST_NUDGE_COOLDOWN_HOURS=24`
- `AUTO_INTEREST_NUDGE_LOOKBACK_DAYS=14`
- `PAID_DAILY_SMS_INTEREST_RESERVE=3` (reserve SMS quota/day for inbound "interested" nudges)
- `TWILIO_TOLLFREE_WATCHDOG_ENABLED=1` (default on in live job)
- `TWILIO_TOLLFREE_AUTOFIX_ENABLED=1` (default on; fix known editable rejection patterns such as `30485`)
- `TWILIO_TOLLFREE_AUTOFIX_ERROR_CODES=30485`
- `TWILIO_TOLLFREE_STALE_REVIEW_HOURS=24`
- `TWILIO_TOLLFREE_ALERT_COOLDOWN_HOURS=12` (dedupe repeated identical alerts)
- `TWILIO_TOLLFREE_NOTIFY_ON_STATUS_CHANGE=1`
- `TWILIO_TOLLFREE_NOTIFY_ON_APPROVED=1`
- `PRIORITY_KICKOFF_URL=https://buy.stripe.com/...` (optional override for payment CTA in interested auto-replies)
- `HIGH_INTENT_OUTREACH_ONLY=1` (default on; tighten to warmer leads)
- `HIGH_INTENT_SKIP_COLD_EMAIL=1` (default on; suppress initial cold emails in high-intent mode)
- `HIGH_INTENT_EMAIL_MIN_SCORE=80`
- `DAILY_CALL_LIST_STATUSES=replied,contacted,new`
- `DAILY_CALL_LIST_MIN_SCORE=80`
- `DAILY_CALL_LIST_EXCLUDE_ROLE_INBOX=1`
- `AUTO_LEAD_HYGIENE_ENABLED=1` (default on; marks invalid emails as `bad_email` before deliverability gating)
- `AUTO_LEAD_HYGIENE_MX_CHECK=1` (default on; can disable for faster/lighter runs)
- `AUTO_LEAD_HYGIENE_SMTP_PROBE=0` (default off; slow)
- `AUTO_LEAD_HYGIENE_CALL_FILTER_ENABLED=1` (default on; drops bad-phone/bad-email artifacts from pre-dial list)
- `AUTO_LEAD_HYGIENE_SAMPLE_LIMIT=20` (max sanitized samples retained in daily report)
- `AUTO_LEAD_HYGIENE_REPORT_PATH=autonomy/state/lead_hygiene_removal_<YYYY-MM-DD>.json` (daily artifact)
- `AUTO_LEAD_HYGIENE_REPORT_LATEST_PATH=autonomy/state/lead_hygiene_removal_latest.json`

Run the toll-free watchdog on demand:
```bash
python3 autonomy/tools/twilio_tollfree_watchdog.py --dotenv .env --exit-on-alert
```

Install hourly watchdog scheduling (macOS launchd):
```bash
python3 autonomy/tools/install_launchd_tollfree_watchdog.py
```

## Lead Generation (Broward County)
`autonomy/tools/lead_gen_broward.py` generates CSV leads for CallCatcher Ops using Google Places.

Example:
```bash
export GOOGLE_PLACES_API_KEY=...
python autonomy/tools/lead_gen_broward.py --limit 30
```

## Scoreboard
View local pipeline counts (leads + emails + bookings/payments):

```bash
python3 autonomy/tools/scoreboard.py
```

Record an opt-out email (when someone requests unsubscribe):

```bash
python3 autonomy/tools/opt_out.py --email someone@example.com
```

Optional analytics/revenue snapshots (requires credentials + deps):

```bash
pip install -r autonomy/tools/requirements.txt
GA4_PROPERTY_ID=... python3 autonomy/tools/ga4_report.py --days 7
STRIPE_SECRET_KEY=... python3 autonomy/tools/stripe_report.py --days 30 --amount-usd 249
```

## Report Delivery (Email vs ntfy)
`autonomy/tools/live_job.py` supports delivering the daily report via email and/or ntfy.

Set in local `.env`:
- `REPORT_DELIVERY=email|ntfy|both|none` (default: `email`)
- `NTFY_SERVER=https://ntfy.sh` (optional; for `REPORT_DELIVERY=ntfy|both`)
- `NTFY_TOPIC=topic-name[,another-topic]` (required for `REPORT_DELIVERY=ntfy|both`)

## Agent Commerce (Lightweight, Non-Crypto)
Twilio API calls now include lightweight agent identity headers plus optional request signing and per-call metering.

Set in local `.env`:
- `AGENT_COMMERCE_AGENT_ID=agent.callcatcherops.v1` (optional override)
- `AGENT_COMMERCE_PROTOCOL=acp-lite/2026-02` (optional override)
- `AGENT_COMMERCE_SIGNING_KEY=...` (optional; enables `X-Agent-Signature` HMAC header)
- `AGENT_COMMERCE_METERING_ENABLED=1` (default on)
- `AGENT_API_METER_FILE=autonomy/state/agent_api_metering.jsonl` (optional override; must stay under `autonomy/state`)

This provides:
- request-level API metering (`status_code`, `duration_ms`, `request_bytes`)
- consistent agent identity headers across autonomous Twilio traffic
- compatibility with future pay-per-call/accounting models without adopting crypto rails today
