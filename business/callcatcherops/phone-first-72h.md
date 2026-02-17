# Phone-First Execution (Next 72 Hours)

As-of: 2026-02-15 (UTC)

Goal: book baseline calls and close 1 pilot. Email is supporting only.

## Assets (Send These Every Time)
- Baseline example (PDF): https://callcatcherops.com/callcatcherops/baseline-example.pdf
- Dentist page: https://callcatcherops.com/callcatcherops/dentist.html
- Baseline intake: https://callcatcherops.com/callcatcherops/intake.html
- Book baseline call: https://calendly.com/igorganapolsky/audit-call

## Call List (One Vertical With Phone Numbers)
Generate a call list CSV (gitignored):
```bash
python3 autonomy/tools/call_list.py \
  --sqlite autonomy/state/autonomy_live.sqlite3 \
  --services "Dentist" \
  --limit 200
```

Open the output under `autonomy/state/` and call the rows where:
- `lead_status=new` or `lead_status=contacted`
- `opted_out=no`
- `phone` is present

Recommended: track outcomes directly in the CSV columns:
- `call_status`
- `call_attempted_at`
- `call_outcome`
- `baseline_yes`
- `baseline_call_time`
- `pilot_yes`
- `notes`

Optional: also log outcomes into the DB (so the daily report can show call counts):
```bash
python3 autonomy/tools/log_call.py --email "lead@example.com" --outcome voicemail --notes "Front desk; owner not in"
```

## Call Script (30 Seconds)
1. Permission + context
   “Hey, is this the front desk? Quick question. I’m Igor with CallCatcher Ops.”

2. Problem (pick the vertical)
   Dentist:
   “When a new patient calls during lunch or after-hours and hits voicemail, many just call the next office. They don’t leave a voicemail.”

   Med spa:
   “When a new client calls after-hours or while your team is in treatment rooms, they usually don’t leave a voicemail. They call the next med spa.”

3. Offer (low friction)
   “I can run a free 1-page baseline: where calls are falling through and what recovery would look like.”

4. Close (one simple next step)
   “Do you want me to send the example baseline and book 15 minutes?”

If yes:
- “Great. What’s the best email to send it to?”
- “And does tomorrow morning or afternoon work for the 15-minute baseline call?”

## Voicemail (10 Seconds)
“Hi, this is Igor with CallCatcher Ops. I’m calling about missed new-client calls. I can run a free 1-page baseline for your med spa. Call me back at {{Phone}}.”

## Post-Voicemail Follow-Up (Email)
Subject: Just tried calling — missed calls

Body:
- 1 line of context (“Just tried you by phone…”)
- Example baseline PDF link
- Calendly booking link

Use the template in `business/callcatcherops/outreach.md`.

## Targets (Concrete)
- Today: 10 calls
- Next 72 hours: 30 calls total
- Minimum win: 1 baseline call booked
- Stretch win: 1 free pilot agreed (in exchange for testimonial + permission to publish a case study)
