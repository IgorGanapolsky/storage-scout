# CallCatcher Ops - Claude Configuration

## Project Overview
CallCatcher Ops is a missed-call recovery and appointment booking offer for local service businesses. This repo also contains outreach automation and digital product landing pages.

## User Mandates
- Never argue with the user.
- If an external system requires a human action (payment, captcha, identity), proceed to the final step and report the exact blocking point in one line.
- Use local `.env` for secrets; never commit `.env` to git.

## Architecture
- `docs/callcatcherops/` - Marketing site (GitHub Pages)
- `autonomy/` - Outreach engine (CSV leads + SMTP, dry-run default)
- `business/callcatcherops/` - Pricing, outreach scripts, deployment notes
- `docs/` - Gumroad product landing pages
- `tools_rental/` - Tools arbitrage experiments (optional)

## Commands
### Outreach Engine
```bash
python3 autonomy/run.py
```

### Lead Generation (Broward County)
```bash
export GOOGLE_PLACES_API_KEY=...
python3 autonomy/tools/lead_gen_broward.py --limit 30
```

### Tools Rental API (Optional)
```bash
python3 tools_rental/api_server.py
```

## Git Workflow
- `main` - Releases only
- `develop` - Default working branch
- All changes via PRs to `develop`

## Coding Standards
- Use environment variables for secrets (never commit tokens)
- Keep automation scripts small and auditable
- Add tests when new logic is non-trivial

## Testing
- No automated test suite configured.
- CI runs `ruff` on `tools_rental/` and `digital_products/`.

## Security
- Secrets stored in `.env` (gitignored)
- Never commit PII or credentials

## File Structure
```
storage/
├── .claude/
├── .github/workflows/
├── autonomy/
├── business/
├── docs/
└── tools_rental/
```

## SESSION CONTINUITY

**On every session start, Claude MUST:**

1. Read `.claude/RALPH_STATE.md` to see what was being worked on
2. Check `gh pr list --state open` for pending PRs
3. Resume incomplete work WITHOUT asking the user

If user says "continue" or "continue where you left off":
- Read RALPH_STATE.md immediately
- Resume the active work or pending tasks
- Never say "I don't have context" - the context IS in the state file

## AUTONOMOUS EXECUTION (Ralph Mode 2026)

**CRITICAL: Claude MUST execute autonomously without asking for permission.**

When given ANY multi-file task (implement, add feature, refactor, build, etc.):

1. **Create branch immediately**: `git checkout -b ralph/$(date +%Y%m%d-%H%M%S)`
2. **Implement the changes** - Write all necessary code
3. **Run checks**: `pip install ruff && ruff check tools_rental/ digital_products/ --select E,F,W --ignore E501`
4. **If checks FAIL**: Analyze error → Fix code → Run checks again (LOOP)
5. **If checks PASS**: Commit with `Ralph: <description>`
6. **Push**: `git push -u origin <branch>`
7. **Create PR**: `gh pr create --base develop --title "Ralph: <desc>"`
8. **Auto-merge**: `gh pr merge --auto --squash`

**DO NOT:**
- Ask "should I proceed?"
- Ask "would you like me to..."
- Wait for confirmation
- Stop after partial implementation

**DO:**
- Execute the full loop until checks pass
- Commit after each successful fix
- Create PR and enable auto-merge
- Report completion with PR link

Required checks for merge: `Python Quality`, `Security`
Optional (won't block): SonarCloud, Claude Review, Seer

**After completing any task:**
- Update `.claude/RALPH_STATE.md` with current status
- This ensures the next session knows where to continue
