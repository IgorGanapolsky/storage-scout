import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[2]
# Direct path to the actual DB in the parent project state
DB_PATH = REPO_ROOT.parent / "autonomy" / "state" / "leads.db"
OUTPUT_PATH = REPO_ROOT / "docs" / "status.html"

def generate():
    total_leads = contacted = audits = 0
    actions = []
    
    # Try to find the DB in common locations
    actual_db = DB_PATH
    if not actual_db.exists():
        actual_db = REPO_ROOT / "autonomy" / "state" / "leads.db"

    if actual_db.exists():
        conn = sqlite3.connect(actual_db)
        conn.row_factory = sqlite3.Row
        try:
            total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            contacted = conn.execute("SELECT COUNT(*) FROM leads WHERE status='contacted'").fetchone()[0]
            audits = conn.execute("SELECT COUNT(*) FROM actions WHERE action_type='audit.complete'").fetchone()[0]
            actions = conn.execute("SELECT ts, action_type, payload_json FROM actions ORDER BY ts DESC LIMIT 10").fetchall()
        except sqlite3.OperationalError:
            pass
    
    html = f"""
    <html>
    <head>
        <title>CallCatcher Ops - Live Status</title>
        <meta http-equiv="refresh" content="300">
        <style>
            body {{ font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6; color: #333; }}
            .card {{ border: 1px solid #ddd; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .stat {{ font-size: 2em; font-weight: bold; color: #007bff; }}
            .label {{ color: #666; text-transform: uppercase; font-size: 0.8em; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px; border-bottom: 1px solid #eee; text-align: left; }}
            .status-live {{ color: #28a745; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>🚀 CallCatcher Ops: Engine Status</h1>
        <p class="status-live">● ENGINE IS LIVE & AUTONOMOUS</p>
        <p>Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px;">
            <div class="card"><div class="label">Total Leads</div><div class="stat">{total_leads}</div></div>
            <div class="card"><div class="label">Pitches Sent</div><div class="stat">{contacted}</div></div>
            <div class="card"><div class="label">Audits Run</div><div class="stat">{audits}</div></div>
        </div>

        <div class="card">
            <h2>Recent Activity</h2>
            <table>
                <tr><th>Time</th><th>Action</th><th>Details</th></tr>
    """
    
    for a in actions:
        try:
            payload = json.loads(a['payload_json'])
            detail = payload.get('company') or payload.get('lead_id') or ""
            html += f"<tr><td>{a['ts']}</td><td>{a['action_type']}</td><td>{detail}</td></tr>"
        except: continue
        
    html += """
            </table>
        </div>
        <p><small>Sarah is active on <b>+17547145117</b></small></p>
    </body>
    </html>
    """
    
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(f"Dashboard generated at {OUTPUT_PATH}")

if __name__ == "__main__":
    generate()
