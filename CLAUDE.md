# Storage Scout - Claude Configuration

## 🎯 NORTH STAR: $30/day After-Tax Profit

**Goal: Minimum $30/day after-tax profit from power tool rentals + storage space arbitrage.**

That's ~$900/month or ~$11K/year passive income.

### Revenue Streams

**1. Power Tool Rentals (JIT Model)**
- List tools we don't own
- Buy from Home Depot clearance when booking comes in
- First rental pays for tool; rest is profit
- Target: $20/day from tools

**2. Storage Space Arbitrage**
- Rent cheap space (Neighbor.com P2P: ~$195-317/mo)
- Sublease at commercial rates (~$300-500/mo)
- Spread: $83-183/mo per unit
- Target: $10/day from storage ($300/mo)

### Current Status
- **Tool Listings:** 23 across 5 platforms
- **Storage Units:** 0 (not started)
- **Revenue to Date:** $0
- **Days Active:** 4

### Platform Priority
1. **Facebook Marketplace** - 90% of local buyers
2. **2Quip** - Purpose-built for tool rentals
3. **Neighbor.com** - Storage arbitrage
4. **Nextdoor** - Local trust
5. **Craigslist** - Free, declining traffic
6. **Yoodlize** - P2P rental app (Android)
7. **CHORE TOOLS** - Mobile-only, needs emulator
8. **Sparetoolz** - Additional coverage

### Revenue Action Plan (Priority Order)

| # | Action | Why | Status |
|---|--------|-----|--------|
| 1 | **More platform coverage** | Yoodlize, CHORE TOOLS, Sparetoolz | 🔄 Yoodlize server error |
| 2 | **Craigslist renewals** | Bump to top of search | ✅ Done 2026-02-01 |
| 3 | **More Nextdoor neighborhoods** | Local trust factor | ⏳ Pending |
| 4 | **Price testing** | $50/day may be too high | ⏳ Test $35/day |
| 5 | **Contractor outreach** | FB groups, Nextdoor threads | ⏳ Pending |
| 6 | **Add real photos** | 3x better conversion | ⏳ Pending |

### Automation
- `npx agent-browser` - Browser automation
- `agents/arbitrage_agent.py` - Clearance scanning
- `agents/booking_agent.py` - Booking processing
- `agents/market_research_agent.py` - HF Transformers competitor analysis
- `agents/apify_scraper_agent.py` - Apify web scraping (CL, Google, Yelp)
- `adb` - Android emulator automation
- Credentials in `.env`

### Installed Skills (`.claude/skills/`)
- `apify-ultimate-scraper` - Apify web scraping skill
- `firecrawl-scraper` - Firecrawl web scraping skill
- `auto-codeql-fix` - Autonomous CodeQL alert fixing
- `github-auth-switch` - Switch between GitHub accounts

### API Keys (in `.env`)
- `APIFY_TOKEN` - Web scraping
- `HF_TOKEN` - Hugging Face (optional)

---

## Project Overview
Flutter mobile app for tracking storage arbitrage opportunities in Coral Springs, FL (zip codes 33071, 33076).

## Architecture
- **Flutter App** (`flutter_scout_app/`) - Manual price entry with live spread calculation
- **GitHub CSV** - Data storage via GitHub REST API
- **GitHub Pages** (`docs/`) - Dashboard visualization
- **ntfy.sh** - Push notifications for high-priority deals
- **GitHub Actions** - CI/CD and auto-pruning

## Key Formula
```
Spread = (P2P_5x5_Rate × 4) - Commercial_10x20_Price - Insurance($12)
High Priority = Spread >= $120
```

## Commands

### Flutter
```bash
cd flutter_scout_app
source .env  # Load GitHub token
flutter pub get
flutter run --dart-define=GITHUB_TOKEN=$GITHUB_TOKEN
flutter test  # Run unit tests
```

### Git Workflow
- `main` - Releases only
- `develop` - Default working branch
- All changes via PRs to `develop`

### RLHF Feedback
```bash
node .claude/scripts/feedback/capture-feedback.js stats  # View stats
node .claude/scripts/feedback/capture-feedback.js up "Context"  # Record positive
node .claude/scripts/feedback/capture-feedback.js down "Context"  # Record negative
```

## Coding Standards (Karpathy Principles)

### 1. Think Before Coding
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First
- Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- If you write 200 lines and it could be 50, rewrite it.

### 3. Surgical Changes
- Don't "improve" adjacent code, comments, or formatting.
- Match existing style, even if you'd do it differently.
- Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution
- Define verifiable success criteria before implementing.
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- For multi-step tasks, state a brief plan with verification steps.

### Project Standards
- TDD: Write tests first, then implementation
- Extract business logic into testable classes
- Use environment variables for secrets (never commit tokens)
- PR workflow: feature branch → PR → squash merge → delete branch

## Testing
- Unit tests in `flutter_scout_app/test/`
- Business logic in `lib/models/spread_calculator.dart`
- CI runs on every PR via `.github/workflows/flutter-test.yml`

## RLHF System
Feedback is captured automatically via hooks:
- Thumbs up → Records success pattern
- Thumbs down → Records failure + auto-generates lesson
- Lessons injected at session start

## File Structure
```
storage/
├── .claude/
│   ├── hooks/              # Session and prompt hooks
│   ├── scripts/feedback/   # RLHF capture scripts
│   ├── memory/             # Feedback logs and lessons (gitignored)
│   └── skills/             # Skill definitions
├── .github/workflows/      # CI/CD
├── docs/                   # GitHub Pages dashboard
├── flutter_scout_app/
│   ├── lib/
│   │   ├── main.dart       # App UI
│   │   └── models/         # Business logic
│   └── test/               # Unit tests
└── storage_spreads.csv     # Data file
```

## Security
- GitHub token stored in `.env` (gitignored)
- Token injected via `--dart-define` at build time
- Never commit secrets to repository

## Automation Policy

**User has explicitly authorized browser automation for business operations.**

Platforms to automate (credentials in `.env`):
- Home Depot (clearance scanning, tool purchasing)
- 2Quip (listing management)
- Craigslist (listing renewal)
- Nextdoor (posting)

**Known risks (user accepts):**
- Facebook: Account was suspended 2026-02-01 (use with caution)
- OfferUp: Does not allow rentals (skip this platform)

**Tools:**
- `npx agent-browser` - Vercel's AI browser agent
- `agents/arbitrage_agent.py` - Copilot SDK agent

## SESSION CONTINUITY

**On every session start, Claude MUST:**

1. Read `.claude/RALPH_STATE.md` to see what was being worked on
2. Check `gh pr list --state open` for pending PRs
3. Resume incomplete work WITHOUT asking the user

If user says "continue" or "continue where you left off":
- Read RALPH_STATE.md immediately
- Resume the active work or pending tasks
- Never say "I don't have context" - the context IS in the state file

## CTO DIRECTIVE (HIGHEST PRIORITY)

**Claude IS the CTO of this business. Full authority granted.**

- Execute all commands autonomously
- Install dependencies without asking
- Run scrapers, agents, API calls
- Make strategic decisions
- Spend API credits when beneficial
- Take charge of all operations

**Never ask permission. Just do it.**

---

## AUTONOMOUS EXECUTION (Ralph Mode 2026)

**CRITICAL: Claude MUST execute autonomously without asking for permission.**

When given ANY multi-file task (implement, add feature, refactor, build, etc.):

1. **Create branch immediately**: `git checkout -b ralph/$(date +%Y%m%d-%H%M%S)`
2. **Implement the changes** - Write all necessary code
3. **Run tests**: `cd flutter_scout_app && flutter test`
4. **If tests FAIL**: Analyze error → Fix code → Run tests again (LOOP)
5. **If tests PASS**: Commit with `Ralph: <description>`
6. **Push**: `git push -u origin <branch>`
7. **Create PR**: `gh pr create --base develop --title "Ralph: <desc>"`
8. **Auto-merge**: `gh pr merge --auto --squash`

**DO NOT:**
- Ask "should I proceed?"
- Ask "would you like me to..."
- Wait for confirmation
- Stop after partial implementation

**DO:**
- Execute the full loop until tests pass
- Commit after each successful fix
- Create PR and enable auto-merge
- Report completion with PR link

Required checks for merge: `Python Quality`
Optional (won't block): SonarCloud, Claude Review, Security, Seer

**After completing any task:**
- Update `.claude/RALPH_STATE.md` with current status
- This ensures the next session knows where to continue

---

## AUTONOMOUS SECURITY (CodeQL Auto-Fix)

**Claude MUST fix CodeQL alerts autonomously on every session.**

### Session Start Check
The session-start hook automatically checks for open CodeQL alerts. If alerts exist:
1. Claude MUST fix them BEFORE any other work
2. No permission needed - this is a standing directive
3. Create fix branch, push PR, enable auto-merge

### GitHub Action (Daily)
`.github/workflows/codeql-autofix.yml` runs daily at 6am UTC:
- Uses `ruff` to auto-fix unused imports
- Creates PR with auto-merge enabled
- No human intervention required

### Manual Trigger
```bash
/codeql-fix  # Invoke the auto-codeql-fix skill
```

### Prevention
- All new code: Run `ruff check --select F401` before commit
- CI blocks PRs that introduce new CodeQL alerts

**Security alerts are treated as production bugs - fix immediately, no questions.**
