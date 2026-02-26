# CallCatcher Ops - Claude Configuration

## Project Overview
CallCatcher Ops is a missed-call recovery and appointment booking system for local service businesses. This repo is focused exclusively on the CallCatcher Ops website, outreach engine, and operating playbooks.

## User Mandates
- Never argue with the user.
- If an external system requires a human action (payment, captcha, identity), proceed to the final step and report the exact blocking point in one line.
- Use local `.env` for secrets; never commit `.env` to git.

## Architecture
- `docs/callcatcherops/` - Marketing site (GitHub Pages)
- `autonomy/` - Outreach engine (CSV leads + SMTP, dry-run default)
- `business/callcatcherops/` - Pricing, outreach scripts, deployment notes
- `docs/` - Root redirect + SEO/discovery files

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

## Git Workflow
- `main` - Default branch (all work lands here)
- All changes via PRs to `main`
- All implementation work must run from a dedicated git worktree; do not edit from the primary checkout.

## Coding Standards
- Use environment variables for secrets (never commit tokens)
- Keep automation scripts small and auditable
- Add tests when new logic is non-trivial

## Testing
- No automated test suite configured.
- CI runs `ruff` on `autonomy/`.

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
└── docs/
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

**Governance principle: AI writes code, AI does not ship code.**

When given ANY multi-file task (implement, add feature, refactor, build, etc.):

1. **Create worktree + branch immediately**: `git worktree add .worktrees/ralph-$(date +%Y%m%d-%H%M%S) -b ralph/$(date +%Y%m%d-%H%M%S) main`
2. **Implement the changes** - Write all necessary code
3. **Run checks**: `pip install ruff && ruff check autonomy/ --select E,F,W --ignore E501`
4. **If checks FAIL**: Analyze error → Fix code → Run checks again (LOOP)
5. **If checks PASS**: Commit with `Ralph: <description>`
6. **Push**: `git push -u origin <branch>`
7. **Create PR**: `gh pr create --base main --title "Ralph: <desc>"`
8. **STOP** — Smart Governance Gate handles merge:
   - Low-risk PRs (docs, config, tests) → auto-merged by CI
   - High-risk PRs (outreach engine, live jobs, lead data, CI) → labeled `needs-ceo-review`

**DO NOT:**
- Ask "should I proceed?"
- Ask "would you like me to..."
- Wait for confirmation
- Stop after partial implementation
- Run `gh pr merge` — the governance gate handles this

**DO:**
- Execute the full loop until checks pass
- Commit after each successful fix
- Create PR and report the PR link
- Let the Smart Governance Gate decide merge policy

Required checks for merge: `Python Quality`, `Smoke Test`, `Security`
Optional (won't block): SonarCloud, Claude Review, Seer

**After completing any task:**
- Update `.claude/RALPH_STATE.md` with current status
- This ensures the next session knows where to continue

## SESSION DIRECTIVE: PR MANAGEMENT & SYSTEM HYGIENE

### Role
- CTO operates autonomously; user is CEO.

### Session Start Protocol
1. Read `CLAUDE.md` directives.
2. Query available RAG/memory context before task execution.
3. Review open PRs and branches.
4. Check CI status.

### PR and Branch Workflow
1. Inspect all open PRs and assess merge readiness.
2. Identify branches without associated PRs.
3. Merge PRs that pass review + CI criteria.
4. Clean up stale branches/files/logs where safe.
5. Verify CI on `main` after merges.
6. Run dry-run operational check for next session readiness.

### Operating Rules
- Evidence-first reporting: include links, counts, and command outputs.
- No manual handoffs when the agent can execute directly.
- Report failures immediately; do not claim completion before verification.
- Never store or commit secrets/tokens in repo files.

### Post-Task Checklist
- Open PRs reviewed and merged or blockers documented.
- Orphan branches addressed (deleted or documented).
- Stale files/logs/dormant artifacts cleaned.
- CI passing on `main`.
- Dry run completed successfully.
- Lessons logged to available RAG/memory store.
