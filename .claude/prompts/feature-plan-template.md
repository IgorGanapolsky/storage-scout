# Feature Plan Template (Plan -> Implement -> Validate)

## Plan
- Objective:
- User-facing impact:
- Files expected to change:
- Risks:

## Implement
- Step 1:
- Step 2:
- Step 3:

## Validate
- [ ] Run fast repo checks:
  - `./.claude/scripts/throughput-quick-checks.sh`
- [ ] Run architecture/contracts checks:
  - `python3 .github/scripts/check_architecture.py`
  - `python3 .github/scripts/check_twilio_contracts.py`
- [ ] Run full browser funnel regression:
  - `npm run e2e:test`
- [ ] Attach/report artifacts from:
  - `.claude/artifacts/e2e/<timestamp>/report.md`

