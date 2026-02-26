# Tools Layer Governance (`autonomy/tools/**`)

## Scope
- Applies to all Python code under `autonomy/tools/`.
- Applies to tool entrypoints and helper modules used by those tools.

## Twilio Guardrails (Required)
- Do not import or call the Twilio SDK directly outside approved wrappers.
- Approved wrappers:
  - `autonomy/tools/twilio_autocall.py`
  - `autonomy/tools/twilio_inbox_sync.py`
  - `autonomy/tools/twilio_interest_nudge.py`
  - `autonomy/tools/twilio_sms.py`
  - `autonomy/tools/twilio_tollfree_watchdog.py`
- In approved wrappers, route Twilio HTTP calls through `autonomy.tools.agent_commerce.request_json`.
- Forbidden patterns outside approved wrappers:
  - `from twilio`
  - `import twilio`
  - `Client(`

## Audit Logging (Required)
- Every outbound Twilio side effect must write an audit action via `ContextStore.log_action(...)`.
- Log both success and failure attempts.
- Payload must include:
  - canonical `outcome`
  - Twilio metadata (`sid`/`status` when available)
  - enough context to trace the action (`agent_id`, `action_type`, `trace_id`)

## Outcome Contract (Required)
- Canonical call outcomes for tool logic: `spoke`, `voicemail`, `no_answer`, `failed`.
- New branches must map into canonical outcomes (or document a migration plan before merge).
- Avoid silent fallthrough paths that skip outcome assignment.

## Change Checklist
- No direct Twilio SDK usage in `autonomy/tools/**`.
- Twilio side effects are audit-logged.
- Outcome mapping covers `spoke|voicemail|no_answer|failed`.
- Matching tests are added/updated in `autonomy/tests/**`.
