# Storage Scout - Claude Configuration

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

## Coding Standards
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
