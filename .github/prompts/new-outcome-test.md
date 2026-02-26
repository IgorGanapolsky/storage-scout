# Prompt: New Outcome Test

Add or update tests for an outcome branch in `autonomy/tools/**`.

## Must Follow
- `.github/instructions/tests-layer.md`
- `.github/instructions/tools-layer.md`

## Required Assertions
- Outcome mapping/counters are correct.
- Audit logging exists for that branch (`ContextStore.log_action(...)` side effect is verified).
- Canonical outcomes remain covered:
  - `spoke`
  - `voicemail`
  - `no_answer`
  - `failed`

## Test Constraints
- Use deterministic fixtures/stubs only.
- No live Twilio network calls.
- Keep tests focused on one branch per test when possible.

## Completion Checklist
- New branch has at least one test.
- Existing matrix coverage is not reduced.
- Failing-path test exists for `failed` behavior when applicable.
