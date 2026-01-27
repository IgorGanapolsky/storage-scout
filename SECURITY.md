# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do NOT** create a public GitHub issue
2. Use GitHub's [Private Vulnerability Reporting](https://github.com/IgorGanapolsky/storage-scout/security/advisories/new)
3. Or email: security@example.com (replace with your email)

### What to include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline
- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days
- **Resolution**: Depends on severity

## Security Best Practices for Contributors

### Secrets Management
- **NEVER** commit tokens, API keys, or credentials
- Use environment variables via `.env` files (gitignored)
- Use `--dart-define` for Flutter build-time secrets

### Code Security
- Validate all user inputs
- Use parameterized queries (if applicable)
- Keep dependencies updated
- Review Dependabot alerts promptly

## Known Security Considerations

### GitHub Token
The app uses a GitHub Personal Access Token for CSV storage:
- Token is loaded via environment variable
- Never hardcoded in source
- Requires only `repo` scope

### Data Privacy
- All RLHF feedback data is stored locally (`.claude/memory/`)
- No sensitive data is committed to the repository
- CSV data contains only storage pricing information
