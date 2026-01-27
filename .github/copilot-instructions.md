# GitHub Copilot Instructions for Storage Scout

This is a Flutter/Dart app for tracking storage arbitrage opportunities in Coral Springs, FL.

## Critical Rules (MUST follow)

### Business Logic
- Spread formula: `(neighborRate * 4) - commercialPrice - insurance`
- Default insurance: $12 (Florida requirement)
- High priority threshold: $120 spread
- Target zip codes: 33071, 33076

### Security
- NEVER hardcode secrets, API keys, or tokens
- GitHub token MUST use `String.fromEnvironment('GITHUB_TOKEN')`
- Build with: `flutter run --dart-define=GITHUB_TOKEN=$TOKEN`

### GitHub Integration
- CSV stored at: `data/storage_prices.csv`
- API endpoint: `https://api.github.com/repos/{owner}/{repo}/contents/{path}`
- Always fetch SHA before updating (GET then PUT)

## Code Patterns

### Dart/Flutter
- Use `const` constructors where possible
- File naming: `snake_case.dart`
- Class naming: `PascalCase`
- Use `late final` for lazy initialization
- Prefer immutable data with `final` fields

### State Management
- Use `StatefulWidget` for local state
- Keep business logic in separate calculator classes
- Validate all user inputs

### Testing
- Test files: `*_test.dart`
- Run: `flutter test`
- Use `flutter_test` package

## Project Structure
```
flutter_scout_app/
├── lib/
│   ├── main.dart              # Main app with UI
│   └── models/
│       └── spread_calculator.dart  # Business logic
├── test/
│   └── spread_calculator_test.dart
└── pubspec.yaml
```

## Import Order
1. Dart SDK (`dart:*`)
2. Flutter SDK (`package:flutter/*`)
3. External packages
4. Project imports (`package:storage_scout/*`)
5. Relative imports

## Notifications
- Use ntfy.sh for push notifications
- Topic: `storage-scout-alerts`
- Only notify on high priority spreads (>= $120)
