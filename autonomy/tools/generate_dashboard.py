import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "docs" / "status.html"

# Search these paths in order; first existing DB wins.
_DB_CANDIDATES = [
    REPO_ROOT / "autonomy" / "state" / "autonomy_live.sqlite3",
    REPO_ROOT / "autonomy" / "state" / "autonomy.sqlite3",
]


def _find_db() -> Path | None:
    for p in _DB_CANDIDATES:
        if p.exists():
            return p
    return None


def generate():
    total_leads = contacted = replied = bounced = emails_sent = 0
    bookings = payments = 0
    actions = []

    actual_db = _find_db()
    if actual_db is not None:
        conn = sqlite3.connect(actual_db)
        conn.row_factory = sqlite3.Row
        try:
            total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            contacted = conn.execute("SELECT COUNT(*) FROM leads WHERE status='contacted'").fetchone()[0]
            replied = conn.execute("SELECT COUNT(*) FROM leads WHERE status='replied'").fetchone()[0]
            bounced = conn.execute("SELECT COUNT(*) FROM leads WHERE status='bounced'").fetchone()[0]
            emails_sent = conn.execute(
                "SELECT COUNT(*) FROM actions WHERE action_type='email.send'"
            ).fetchone()[0]
            bookings = conn.execute(
                "SELECT COUNT(*) FROM actions WHERE action_type='conversion.booking'"
            ).fetchone()[0]
            payments = conn.execute(
                "SELECT COUNT(*) FROM actions WHERE action_type='conversion.payment'"
            ).fetchone()[0]
            actions = conn.execute(
                "SELECT ts, action_type, payload_json FROM actions ORDER BY ts DESC LIMIT 15"
            ).fetchall()
        except sqlite3.OperationalError:
            pass

    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    db_label = str(actual_db.name) if actual_db else "none"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>CallCatcher Ops - Live Dashboard</title>
    <meta http-equiv="refresh" content="300">
    <style>
        body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; color: #333; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; margin: 20px 0; }}
        .card {{ border: 1px solid #ddd; padding: 16px; border-radius: 8px; text-align: center; }}
        .stat {{ font-size: 2em; font-weight: bold; color: #007bff; }}
        .stat.zero {{ color: #999; }}
        .stat.green {{ color: #28a745; }}
        .label {{ color: #666; text-transform: uppercase; font-size: 0.75em; letter-spacing: 0.05em; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        th, td {{ padding: 8px 10px; border-bottom: 1px solid #eee; text-align: left; font-size: 0.9em; }}
        th {{ color: #666; font-weight: 600; }}
        .live {{ color: #28a745; font-weight: bold; }}
        .meta {{ color: #999; font-size: 0.8em; margin-top: 24px; }}
    </style>
</head>
<body>
    <h1>CallCatcher Ops: Dashboard</h1>
    <p class="live">ENGINE LIVE</p>
    <p style="color:#666;">Last updated: {ts} UTC &middot; DB: {db_label}</p>

    <div class="grid">
        <div class="card"><div class="label">Total Leads</div><div class="stat{' zero' if total_leads == 0 else ''}">{total_leads}</div></div>
        <div class="card"><div class="label">Emails Sent</div><div class="stat{' zero' if emails_sent == 0 else ''}">{emails_sent}</div></div>
        <div class="card"><div class="label">Contacted</div><div class="stat{' zero' if contacted == 0 else ''}">{contacted}</div></div>
        <div class="card"><div class="label">Replied</div><div class="stat{' green' if replied > 0 else ' zero'}">{replied}</div></div>
        <div class="card"><div class="label">Bounced</div><div class="stat{' zero' if bounced == 0 else ''}">{bounced}</div></div>
        <div class="card"><div class="label">Bookings</div><div class="stat{' green' if bookings > 0 else ' zero'}">{bookings}</div></div>
        <div class="card"><div class="label">Payments</div><div class="stat{' green' if payments > 0 else ' zero'}">{payments}</div></div>
    </div>

    <h2>Recent Activity</h2>
    <table>
        <tr><th>Time</th><th>Action</th><th>Details</th></tr>
"""

    for a in actions:
        try:
            payload = json.loads(a['payload_json'])
            detail = payload.get('company') or payload.get('email') or payload.get('lead_id') or ""
            html += f"        <tr><td>{a['ts']}</td><td>{a['action_type']}</td><td>{detail}</td></tr>\n"
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    html += """    </table>

    <p class="meta">CallCatcher Ops &middot; Coral Springs, FL &middot; hello@callcatcherops.com</p>
</body>
</html>
"""

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(f"Dashboard generated at {OUTPUT_PATH} (db={db_label}, leads={total_leads}, emails={emails_sent})")


if __name__ == "__main__":
    generate()
