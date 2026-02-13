# Strategy Truth Loop (CallCatcher Ops)

Use this loop for strategic questions about money, viability, and execution.

## Goal
- Record every strategic response.
- Compare against prior responses for consistency/truth signals.
- Produce a concrete action plan with deadlines and gates.

## Command
```bash
# IMPORTANT: if your response includes money like "$0" or "$249", do NOT pass it
# directly as a double-quoted CLI arg (shells expand $0 -> your shell path).
# Use files instead to avoid accidental expansion.
python3 .claude/scripts/feedback/strategy_truth_loop.py \
  --question-file .claude/tmp/strategy-question.txt \
  --response-file .claude/tmp/strategy-response.txt \
  --source "EVIDENCE_LINK_OR_NOTES"
```

## Outputs
- Log: `.claude/memory/feedback/strategy-response-log.jsonl`
- Summary: `.claude/memory/feedback/strategy-truth-summary.json`
- Plan artifacts: `.claude/memory/plans/*.md`

## Required Response Standard
1. Include an as-of date for any money/revenue claim.
2. Include explicit confidence level for forecasts.
3. Include at least one evidence source when available.
4. Include measurable gates and stop/pivot criteria.
