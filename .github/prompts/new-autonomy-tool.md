# Prompt: New Autonomy Tool

Design and implement a new tool under `autonomy/tools/` with CallCatcher Ops governance.

## Must Follow
- `.github/copilot-instructions.md`
- `.github/instructions/tools-layer.md`
- `.github/instructions/tests-layer.md`

## Requirements
- No direct Twilio SDK usage in `autonomy/tools/**` (`from twilio`, `import twilio`, `Client(` are disallowed).
- Any Twilio side effect must write `ContextStore.log_action(...)`.
- Outcome paths must use canonical states: `spoke`, `voicemail`, `no_answer`, `failed`.
- Add tests for every new outcome branch.

## Deliverables
- Minimal tool implementation with clear input validation.
- Tests in `autonomy/tests/**` for all changed/new branches.
- Brief note in PR summary listing:
  - outcome branches added/changed
  - audit actions emitted
  - proof no direct Twilio SDK calls were added

## Self-Check Commands
- `rg -n "from twilio|import twilio|Client\\(" autonomy/tools`
- `rg -n "log_action\\(" autonomy/tools`
- `pytest -q autonomy/tests -k "twilio or outcome"`
