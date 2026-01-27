# Storage Scout

A Flutter app for manually tracking storage arbitrage opportunities in the Coral Springs, FL market.

## Architecture

| Component | Technology | Role |
|-----------|------------|------|
| Input | Flutter Mobile App | Rapid manual entry & spread calculation |
| Storage | GitHub Repo (CSV) | Acts as your "database" |
| Analysis | GitHub Pages | Visual dashboard for tracking trends |
| Alerts | ntfy.sh | Push notifications for high-profit deals |

## The Spread Formula

```
Spread = (P2P_5x5_Rate × 4) - Commercial_10x20_Price - Insurance
```

- **P2P_5x5_Rate**: Average Neighbor.com rate for 5x5 units (~$65)
- **Commercial_10x20_Price**: What you pay for a 10x20 unit
- **Insurance**: $12/month (Florida mandatory) — waivable with proof of coverage
- **High Priority**: Spread > $120/month

## Setup

### 1. Flutter App

```bash
cd flutter_scout_app
flutter pub get
flutter run
```

Configure in `lib/main.dart`:
```dart
static const String ghToken = 'YOUR_GITHUB_TOKEN';
static const String ghUser = 'YOUR_USERNAME';
static const String ghRepo = 'YOUR_REPO_NAME';
static const String ntfyTopic = 'your_ntfy_topic';
```

### 2. GitHub Token

Create a Personal Access Token with `repo` scope:
1. GitHub → Settings → Developer settings → Personal access tokens
2. Generate new token (classic)
3. Select `repo` scope
4. Copy token to app config

### 3. GitHub Pages Dashboard

1. Go to repo Settings → Pages
2. Source: Deploy from branch
3. Branch: `main`, folder: `/docs`
4. Update `docs/index.html` with your username in the CSV_URL

### 4. ntfy.sh Notifications

1. Install ntfy app on Android/iOS
2. Subscribe to your topic name
3. Use same topic name in app config

## Files

```
storage/
├── flutter_scout_app/      # Mobile app source
│   ├── lib/main.dart       # All app code
│   └── pubspec.yaml        # Dependencies
├── docs/
│   └── index.html          # GitHub Pages dashboard
├── .github/workflows/
│   ├── update-dashboard.yml  # Auto-deploy on CSV change
│   └── prune-csv.yml         # Monthly cleanup (90 days)
└── storage_spreads.csv     # Your data
```

## Target Zip Codes

- **33071** - Coral Springs (University Dr / Sample Rd area)
- **33076** - Coral Springs / Parkland

## License

MIT
