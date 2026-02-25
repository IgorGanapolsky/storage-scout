# Ralph Session State

> Auto-updated by Ralph to track work in progress. Claude reads this on session start.

## Last Updated
2026-02-25T15:32:00Z

## Current Status
**ACTIVE** — Revenue blocker fixed, tech debt cleaned, call pipeline unblocked

## Completed This Session (2026-02-25)

### 1. Revenue Blocker Fix (PR #282 — MERGED)
- Root cause: `default_min_score=80` but `LeadScorer.score()` maxes at 75
- No lead could ever qualify for call list — zero calls for 30 days
- Fix: Lowered default from 80 to 70
- Verified: 11 leads now qualify (proven against real DB)
- .env updated: `DAILY_CALL_LIST_MIN_SCORE=70`, `HIGH_INTENT_CALL_MIN_SCORE=70`
- Stop-loss state reset to match .env thresholds (max_zero_days=14)

### 2. Tech Debt Cleanup (PR #283 — MERGED)
- Fixed non-deterministic message ID in tracking.py (id() returns memory address)
- Moved PIXEL_ENDPOINT to env var
- Removed dead `_render_intake_link()` from agents.py
- Fixed dashboard.yml branch (develop → main)
- Removed 4 stale git worktrees (~200MB)
- Deleted 350+ test artifacts (7.4MB → 304K)
- Unloaded 2 broken launchd jobs (hot_lead_watchdog, sms_pitch_dentists)

### 3. DRY Violations Fix (PR #284 — MERGED)
- Extracted `is_business_hours()` to utils.py (was duplicated in 2 files)
- Consolidated 5 email regex patterns → 2 canonical constants in utils.py
- Replaced hardcoded Calendly/Stripe URLs with env var lookups
- Removed dead `_state_tz()` wrapper
- 10 files changed, net -6 lines

## Pipeline Status

### Call Pipeline: UNBLOCKED
- 11 leads qualify for call list (score >= 70 with phone, non-role-inbox)
- 40 total leads with phone numbers in DB
- AUTO_CALLS_ENABLED=1, MAX_PER_RUN=3
- Stop-loss: unblocked (max_zero_days=14)
- Next live_job run during business hours should produce calls

### Email Pipeline: FLOWING (low volume)
- 11 emails sent in 30 days, 0 replies, 0 bounces
- daily_send_limit: 10

### SMS Pipeline: PENDING VERIFICATION
- Toll-free +18446480144 verification IN_REVIEW

## System State
- CI passing on main (3 PRs merged today)
- Remote branches: 2 (main, develop)
- Tests: 125/125 passing
- State dir: 304K (was 7.4MB)
- Broken launchd jobs: 0 (was 2)
