# GitHub Copilot Setup Checklist (CallCatcher Ops)

## Enable Copilot Features
1. Open repository settings for `IgorGanapolsky/storage-scout`.
2. Enable Copilot Chat/Completions for the repository.
3. Enable Copilot code review in rulesets (optional but recommended).

## Enable Copilot Coding Agent (optional)
1. Allow Copilot to push branches and open PRs.
2. Assign an issue to `@copilot` for autonomous implementation.

## Required Repo Files
- `.github/copilot-instructions.md`
- `.github/workflows/claude-review.yml`

## Validation
1. Open a PR touching `docs/callcatcherops/` or `autonomy/`.
2. Confirm Copilot/Claude reviews trigger.
3. Confirm recommendations align with CallCatcher scope and do not reference removed experiments.
