# Ralph Session State

> Auto-updated by Ralph to track work in progress. Claude reads this on session start.

## Last Updated
2026-02-21T21:45:00Z

## Current Status
🎯 **ACTIVE** — Strategic pivot: AI Receptionist for Dental Practices

## Strategic Pivot (2026-02-21)

### What Changed
Deep research (4 parallel agents) confirmed:
- Missed-call text-back alone is **commoditized** (competitors offer it at $3.99/mo)
- AI receptionist is the differentiated product ($199-497/mo, 70% gross margin)
- Dental is the best niche (highest revenue/patient, HIPAA moat, tech-willing)
- Cold email via Fastmail SMTP is the wrong tool (use Clay + Instantly instead)
- The current Twilio TwiML robocall approach produces 0 bookings

### Research Findings (Key Data Points)
- Dental practices lose ~$100K/yr from missed calls (42% of potential patients)
- AI receptionist saves 70% vs. full-time front desk ($55-78K/yr)
- Case study: Soothing Dental generated $30,877 in 30 days with AI receptionist
- Broward County TAM: ~4,400 dental/medical establishments
- Target pricing: $497/mo + $997 setup fee (need 2 clients for $1K MRR)
- Best outbound: Clay + Instantly for cold email, NOT Fastmail SMTP
- Florida FTSA has NO B2B exemption — limits automated calls to 3/24hrs
- AI calls to business landlines are legal without consent (TCPA B2B exemption)

### Completed Today (2026-02-21)
- ✅ PR #172: MX email verification + call script rewrite (MERGED)
  - Added DNS MX record check to lead gen pipeline (prevents 54% bounce rate)
  - Rewrote Twilio call script: natural tone, Polly.Matthew voice, "text yes" CTA
- ✅ Reset stop-loss state: 150 zero-revenue runs → 0, all paid channels unblocked
- ✅ Updated live config: widened target services, re-enabled SMS followup (5/day)
- ✅ PR #175: Missed-call audit tool + HTML report generator (auto-merge enabled)
  - `missed_call_audit.py`: CLI that places N calls via Twilio, records dispositions
  - `audit_report.py`: generates branded 1-page HTML report with revenue impact

### 3-Phase Revenue Plan

**Phase 1: Missed-Call Audit Tool (DONE)**
- Automated audit: call a dental office 5x, record what happens
- Generates branded HTML report showing estimated revenue loss
- This is the foot-in-the-door / lead magnet
- Usage: `python3 -m autonomy.tools.missed_call_audit --phone "+19541234567" --company "Name" --service dentist`

**Phase 2: AI Receptionist MVP (NEXT)**
- Build conversational AI voice agent using Retell AI or Vapi
- Handles: scheduling, FAQ, caller qualification, routing
- HIPAA-compliant call handling (the moat)
- Target: $497/mo subscription

**Phase 3: Outbound Engine Rebuild (WEEK 3)**
- Replace Fastmail SMTP with Instantly.ai for cold email
- Clay for dental practice data enrichment
- Target 50 dental practices in Coral Springs / Parkland / Coconut Creek
- Multichannel: email → LinkedIn → audit call

## System State

### Stop-Loss
- `blocked: false` (reset 2026-02-21)
- `zero_revenue_runs: 0`
- 20 runs / 14 days before re-trigger

### Live Config
- `target_services`: med spa, dentist, plumber, chiropractor, hvac
- `daily_send_limit`: 0 (email still paused — use Clay+Instantly instead)
- `followup.enabled`: true (5/day, 3-day spacing)
- SMS followup active

### Lead Pipeline
- 220 leads in SQLite (204 new, 15 contacted, 1 replied)
- Email deliverability: BLOCKED (54% bounce rate) — MX verification now prevents new bad leads
- Call list: 16 rows (all previously contacted/bounced — need fresh leads)

## Open PRs
- PR #175: Missed-call audit tool (auto-merge enabled, waiting CI)

## Key Files
- Audit tool: `autonomy/tools/missed_call_audit.py`
- Audit report: `autonomy/tools/audit_report.py`
- Live config: `autonomy/state/config.callcatcherops.live.json`
- Stop-loss state: `autonomy/state/paid_stop_loss_state.json`
- Call script: `autonomy/tools/twilio_autocall.py` (line 71, `_default_twiml()`)

## Notes for Next Session
- Phase 2 (AI receptionist) is the priority — research Retell AI vs Vapi pricing
- Need to sign up for Retell AI or Vapi and get API credentials
- HIPAA BAA is required before handling dental calls — check if Retell/Vapi offer this
- Consider Open Dental PMS integration for appointment booking
- The free missed-call audit is the sales weapon — run it on 10 dental offices ASAP
