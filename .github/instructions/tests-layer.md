# Tests Layer Governance (`autonomy/tests/**`)

## Scope
- Applies to tests covering `autonomy/tools/**`.
- Required for any PR that adds or changes outcome branches.

## Outcome Coverage Rules (Required)
- Tests must explicitly cover canonical outcomes:
  - `spoke`
  - `voicemail`
  - `no_answer`
  - `failed`
- If logic changes outcome mapping, update/add tests in the same PR.

## Branch-Level Test Rules
- Every new outcome branch needs at least one deterministic test.
- Tests must assert both:
  - outcome/counter behavior
  - audit log behavior for the same path

## Twilio Test Isolation
- No live Twilio network calls in unit tests.
- Stub/mock HTTP responses and status transitions.
- Keep fixtures minimal and reproducible.

## PR Checklist
- Canonical outcome matrix still passes.
- New branch paths are tested.
- Audit logging assertions are present for changed Twilio execution paths.
