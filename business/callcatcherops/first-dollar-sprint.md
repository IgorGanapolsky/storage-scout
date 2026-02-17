# First Dollar Sprint (Phone-First)

Start: 2026-02-18 (Wed)  
End: 2026-03-03 (Tue)  
Cadence: 10 workdays (Mon-Fri)

## Single Metric That Matters
- payments_today

Secondary (leading indicators):
- bookings_today
- interested_sms_today

## Daily Targets (minimum viable volume)
- dials_per_day: 60
- blocks: 2 (30 dials late morning, 30 dials late afternoon)

Expected ranges (cold SMB):
- connect_rate: 10-20% (6-12 connects/day)
- decision_maker_connects: 30-60% of connects (2-7/day)
- interested: 10-25% of decision-maker connects (0-2/day)

## Pass/Fail Gates

By Day 3 (2026-02-20, Fri):
- PASS: >= 1 booking OR >= 3 explicit "yes/interested" SMS replies
- FAIL: 0 bookings AND < 3 interested replies
Action if FAIL: change script + narrow segment (higher intent only) the same day.

By Day 7 (2026-02-26, Thu):
- PASS: >= 3 total bookings
- FAIL: < 2 total bookings
Action if FAIL: pivot offer or vertical (stop calling low-intent).

By Day 10 (2026-03-03, Tue):
- PASS (minimum): >= 1 payment
- STRONG PASS: >= 2 payments OR >= 6 bookings with clear "ready to pay" signals
- FAIL: 0 payments after ~600 dials
Action if FAIL: stop and pivot (offer/targeting is wrong, not "more automation").

## Operating Rules (keep the test valid)
- Cold email remains OFF while deliverability is blocked (bounce gate).
- High-intent only:
  - require phone present
  - avoid opted-out leads
  - enforce score threshold (start 80+)
- SMS follow-ups:
  - send only after voicemail OR explicit interest
  - always include opt-out language
- One CTA:
  - baseline booking link first
  - Stripe link only after explicit interest

