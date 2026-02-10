# CallCatcher Ops

Missed-call recovery and appointment booking for local service businesses.

## What's In This Repo
- `docs/callcatcherops/` - Marketing site (GitHub Pages)
- `autonomy/` - Outreach engine (CSV leads + SMTP, dry-run default)
- `business/callcatcherops/` - Pricing, outreach scripts, deployment notes
- `docs/` - Gumroad product landing pages
- `tools_rental/` - Tools arbitrage experiments (optional)

## Quick Start
1. Edit the site: `docs/callcatcherops/index.html`
2. Deploy via GitHub Pages (custom domain handled in `business/callcatcherops/DEPLOYMENT.md`)
3. Copy `autonomy/config.example.json` to a new config
4. Run `python3 autonomy/run.py` (requires SMTP creds to go live)
