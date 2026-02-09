# Autonomous Outreach Engine (Frontier-Ready)

This is a minimal, production-shaped automation engine that mirrors Frontier-style architecture:
- shared business context
- explicit agent identities + permissions
- auditable action ledger
- evaluation hooks

It runs in **dry-run** by default and becomes live when credentials are provided.

## What It Does
- Ingests leads from CSV
- Scores and dedupes
- Generates compliant outreach messages
- Sends via SMTP (or logs in dry-run)
- Records every action in an audit trail

## Files
- `autonomy/config.example.json` - configuration template
- `autonomy/run.py` - entrypoint
- `autonomy/engine.py` - orchestration logic
- `autonomy/context_store.py` - SQLite context store
- `autonomy/providers.py` - lead + email providers
- `autonomy/agents.py` - scoring + message generation

## Notes
- No secrets are committed.
- All actions are written to a JSONL audit log.
- This is intentionally minimal and extensible.
