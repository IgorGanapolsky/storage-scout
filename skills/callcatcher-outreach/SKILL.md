---
name: callcatcher-outreach
description: >
  Missed-call recovery outreach automation for local service businesses —
  lead scoring, multi-step email sequences, compliance, and booking conversion.
triggers:
  - outreach
  - missed call recovery
  - lead outreach
  - email campaign
  - callcatcher outreach
version: 1.0.0
---

# CallCatcher Outreach

## Overview

Automates missed-call recovery outreach for local service businesses. The skill ingests leads from CSV files, scores them by data completeness, runs initial and follow-up email sequences, and tracks every interaction in SQLite. All outbound email is CAN-SPAM compliant with physical address, unsubscribe links, and opt-out enforcement.

## Prerequisites

- **Python 3.11+**
- SMTP credentials set in environment variables (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`)
- Lead CSV file(s) placed in `autonomy/state/`

## Configuration

All settings live in `autonomy/config.callcatcherops.json`. Key schema sections:

| Section | Fields | Purpose |
|---|---|---|
| `mode` | `dry-run` \| `live` | Dry-run logs emails without sending |
| `company` | `name`, `physical_address`, `website`, `phone` | Sender identity and CAN-SPAM address |
| `agent` | `max_emails_per_run`, `min_score` | Throttle volume and quality floor |
| `lead_sources` | Array of CSV paths in `autonomy/state/` | Where to ingest leads |
| `email` | `from_name`, `from_address`, `reply_to`, `subject_templates` | Outbound email settings |
| `followup` | `steps`, `min_days_between`, `max_emails_per_lead` | Multi-step sequence timing |
| `compliance` | `unsubscribe_url`, `physical_address` | CAN-SPAM required fields |
| `storage` | `db_path`, `audit_log_path` | SQLite DB and JSONL audit log locations |

## Workflow

1. **Ingest leads** — Parse CSV files from configured `lead_sources`. Deduplicate by email address. Insert new leads into SQLite.
2. **Score leads** — Assign points by data completeness:
   - Company name present: **+20**
   - Phone number present: **+15**
   - Service type present: **+10**
   - Location present: **+10**
   - Email present: **+20**
   - Maximum score capped at **100**
3. **Initial outreach** — Select unsent leads with score ≥ `min_score`. Render email template with lead-specific merge fields. Send (or log in dry-run mode). Record `sent_at` timestamp.
4. **Follow-up sequence** — For leads that received the initial email but haven't booked:
   - Advance through configurable `steps` (e.g., reminder, value-add, final nudge).
   - Enforce `min_days_between` sends.
   - Stop after `max_emails_per_lead` total emails.
5. **Opt-out check** — Before every send, query the `opt_outs` table. Skip any lead that has unsubscribed.
6. **Audit logging** — Every send/skip event is written to both:
   - JSONL file at `storage.audit_log_path`
   - `audit_log` table in the SQLite database

## Execution

```bash
python3 autonomy/run.py --config autonomy/config.callcatcherops.json
```

Add `--dry-run` to override the config mode and preview without sending.

## Customization

To onboard a new client:

1. **Copy config** — Duplicate `config.callcatcherops.json` and rename for the client.
2. **Set company info** — Fill in `company.name`, `company.physical_address`, `company.website`.
3. **Add lead CSV** — Place the client's lead export in `autonomy/state/` and add the path to `lead_sources`.
4. **Set SMTP credentials** — Export `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` for the client's sending domain.
5. **Tune thresholds** — Adjust `agent.min_score`, `followup.steps`, and `followup.min_days_between` to match the client's sales cadence.

## Compliance

All outbound email satisfies CAN-SPAM requirements:

- **Physical address** — Included in every email footer via `compliance.physical_address`.
- **Unsubscribe link** — Every email contains a one-click unsubscribe URL (`compliance.unsubscribe_url`).
- **Opt-out table** — Unsubscribe clicks are recorded in the `opt_outs` SQLite table. The opt-out check runs before every send with no grace period.
