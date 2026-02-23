#!/usr/bin/env python3
"""Generate a 1-page HTML missed-call audit report from audit results.

The report mirrors the design of baseline-example.html and shows:
- Call-by-call results (answered / voicemail / no answer)
- Estimated annual revenue loss
- Clear CTA to book a demo
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from autonomy.utils import UTC

STATE_DIR = Path(__file__).resolve().parents[1] / "state"

# Average first-visit revenue by service type (conservative estimates).
AVG_APPOINTMENT_VALUE: dict[str, int] = {
    "dentist": 350,
    "med spa": 400,
    "plumber": 250,
    "hvac": 300,
    "chiropractor": 150,
    "electrician": 200,
    "roofing": 500,
    "urgent care": 250,
}

DEFAULT_APPOINTMENT_VALUE = 250
CALLS_PER_DAY_ESTIMATE = 30  # Conservative for a busy local practice.


def _outcome_emoji(outcome: str) -> str:
    return {
        "spoke": "&#9989;",       # green check
        "voicemail": "&#9993;",   # envelope
        "no_answer": "&#10060;",  # red X
        "wrong_number": "&#9888;",  # warning
        "failed": "&#9888;",
    }.get(outcome, "&#8212;")


def _outcome_label(outcome: str) -> str:
    return {
        "spoke": "Answered (human)",
        "voicemail": "Voicemail",
        "no_answer": "No answer / busy",
        "wrong_number": "Wrong number",
        "failed": "Call failed",
    }.get(outcome, outcome)


def generate_audit_report(
    result,
    *,
    output_dir: Path | None = None,
    calls_per_day: int = CALLS_PER_DAY_ESTIMATE,
) -> Path:
    """Generate HTML report and write to disk. Returns the output path."""

    out_dir = output_dir or STATE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    service = (result.service or "").lower()
    appt_value = AVG_APPOINTMENT_VALUE.get(service, DEFAULT_APPOINTMENT_VALUE)

    # Revenue math.
    miss_rate = result.miss_rate_pct / 100.0
    missed_per_day = round(calls_per_day * miss_rate, 1)
    missed_per_week = round(missed_per_day * 5, 1)  # Business days only.
    recovery_rate = 0.30  # Conservative: 30% of missed calls recovered.
    recovered_per_week = round(missed_per_week * recovery_rate, 1)
    revenue_per_week = round(recovered_per_week * appt_value)
    revenue_per_year = revenue_per_week * 52
    lost_per_year = round(missed_per_day * 5 * 52 * appt_value * 0.15)  # 15% would have booked.

    # Build probe rows.
    probe_rows = ""
    for p in result.probes:
        ts = p.attempted_at.split("T")[1][:8] if "T" in p.attempted_at else p.attempted_at
        probe_rows += (
            f"<tr>"
            f"<td>{p.attempt}</td>"
            f"<td class='mono'>{ts}</td>"
            f"<td>{_outcome_emoji(p.outcome)} {_outcome_label(p.outcome)}</td>"
            f"<td>{p.duration_secs}s</td>"
            f"</tr>\n"
        )

    as_of = datetime.now(UTC).strftime("%Y-%m-%d")
    company_display = result.company or "Your Practice"

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>CallCatcher Ops — Missed-Call Audit: {company_display}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Spectral:wght@400;500;600&display=swap" rel="stylesheet"/>
  <style>
    :root {{
      --ink: #0f1c1b; --muted: #3b504d; --mist: #f4f2ed;
      --sage: #bfe6c2; --sea: #5ca4a9; --ember: #ff7a59;
      --shadow: rgba(15,28,27,0.14); --radius: 18px;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Spectral", serif; color: var(--ink); background: #fff; }}
    @page {{ size: letter; margin: 0.5in; }}
    .wrap {{ max-width: 900px; margin: 0 auto; padding: 20px; }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 18px; }}
    .brand {{ display: flex; align-items: center; gap: 12px; font-family: "Space Grotesk", sans-serif; font-weight: 700; }}
    .badge {{ width: 42px; height: 42px; border-radius: 12px; background: linear-gradient(140deg, var(--sea), var(--sage)); box-shadow: 0 10px 24px rgba(92,164,169,0.25); }}
    .meta {{ font-family: "Space Grotesk", sans-serif; color: var(--muted); font-size: 0.95rem; text-align: right; }}
    h1 {{ font-family: "Space Grotesk", sans-serif; font-size: 1.85rem; margin: 6px 0 4px; line-height: 1.15; }}
    .subhead {{ margin: 0 0 12px; color: var(--muted); font-size: 1.02rem; }}
    .panel {{ border-radius: var(--radius); border: 1px solid rgba(15,28,27,0.12); padding: 14px 16px; box-shadow: 0 18px 40px var(--shadow); margin-bottom: 12px; }}
    .numbers {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 10px; }}
    .kpi {{ border-radius: 14px; padding: 10px 12px; background: linear-gradient(140deg, rgba(92,164,169,0.14), rgba(191,230,194,0.18)); border: 1px solid rgba(15,28,27,0.08); }}
    .kpi .label {{ font-family: "Space Grotesk", sans-serif; font-weight: 600; color: var(--muted); font-size: 0.88rem; }}
    .kpi .value {{ font-family: "Space Grotesk", sans-serif; font-weight: 700; font-size: 1.4rem; margin-top: 4px; }}
    .kpi .small {{ color: var(--muted); margin-top: 3px; font-size: 0.88rem; }}
    .kpi-red {{ background: linear-gradient(140deg, rgba(255,122,89,0.12), rgba(255,122,89,0.06)); }}
    h2 {{ font-family: "Space Grotesk", sans-serif; margin: 0 0 10px; font-size: 1.08rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    th {{ font-family: "Space Grotesk", sans-serif; text-align: left; padding: 6px 8px; border-bottom: 2px solid var(--ink); }}
    td {{ padding: 6px 8px; border-bottom: 1px solid rgba(15,28,27,0.08); }}
    .callout {{ margin-top: 10px; border-left: 4px solid var(--ember); padding: 9px 11px; background: rgba(255,122,89,0.07); border-radius: 12px; }}
    .callout strong {{ font-family: "Space Grotesk", sans-serif; }}
    .grid {{ display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 12px; }}
    .footer {{ margin-top: 14px; padding-top: 10px; border-top: 1px solid rgba(15,28,27,0.12); display: flex; justify-content: space-between; gap: 16px; color: var(--muted); font-size: 0.92rem; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.92rem; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin-bottom: 6px; }}
  </style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="badge" aria-hidden="true"></div>
      <div>CallCatcher Ops</div>
    </div>
    <div class="meta">
      Missed-Call Audit<br/>
      <span class="mono">As-of: {as_of}</span>
    </div>
  </header>

  <h1>Missed-Call Audit: {company_display}</h1>
  <p class="subhead">
    We called {company_display} at {result.phone} a total of {result.total_calls} times
    and recorded what happened each time.
  </p>

  <div class="panel">
    <h2>Audit Results</h2>
    <div class="numbers">
      <div class="kpi">
        <div class="label">Calls placed</div>
        <div class="value">{result.total_calls}</div>
      </div>
      <div class="kpi{'  kpi-red' if result.answer_rate_pct < 50 else ''}">
        <div class="label">Answered by human</div>
        <div class="value">{result.answered_human} ({result.answer_rate_pct}%)</div>
      </div>
      <div class="kpi{'  kpi-red' if result.voicemail > 0 else ''}">
        <div class="label">Went to voicemail</div>
        <div class="value">{result.voicemail}</div>
      </div>
      <div class="kpi{'  kpi-red' if result.no_answer > 0 else ''}">
        <div class="label">No answer / busy</div>
        <div class="value">{result.no_answer}</div>
      </div>
    </div>
  </div>

  <div class="panel">
    <h2>Call-by-call detail</h2>
    <table>
      <thead><tr><th>#</th><th>Time (UTC)</th><th>Result</th><th>Ring time</th></tr></thead>
      <tbody>
{probe_rows}
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>Revenue Impact Estimate</h2>
    <div class="numbers">
      <div class="kpi kpi-red">
        <div class="label">Estimated missed calls / week</div>
        <div class="value">{missed_per_week}</div>
        <div class="small">{calls_per_day} calls/day &times; {result.miss_rate_pct}% miss rate &times; 5 days</div>
      </div>
      <div class="kpi kpi-red">
        <div class="label">Estimated lost revenue / year</div>
        <div class="value">${lost_per_year:,}</div>
        <div class="small">{missed_per_week} missed/wk &times; 15% would-book &times; ${appt_value} avg</div>
      </div>
      <div class="kpi">
        <div class="label">Recoverable with text-back</div>
        <div class="value">{recovered_per_week}/week</div>
        <div class="small">30% recovery rate (conservative)</div>
      </div>
      <div class="kpi">
        <div class="label">Recovered revenue / year</div>
        <div class="value">${revenue_per_year:,}</div>
        <div class="small">{recovered_per_week} recovered &times; ${appt_value} &times; 52 weeks</div>
      </div>
    </div>

    <div class="callout">
      <strong>Bottom line:</strong> {company_display} could be losing up to
      <strong>${lost_per_year:,}/year</strong> from missed calls. A missed-call
      AI receptionist recovers an estimated <strong>${revenue_per_year:,}/year</strong>
      for <strong>$497/month</strong> ($5,964/year) &mdash; a
      <strong>{round(revenue_per_year / 5964, 1)}x ROI</strong>.
    </div>
  </div>

  <div class="grid">
    <div class="panel">
      <h2>What we recommend</h2>
      <ul>
        <li><strong>AI receptionist</strong> answers every call 24/7 &mdash; qualifies callers, books appointments, answers FAQs</li>
        <li><strong>Missed-call text-back</strong> within 60 seconds when staff can't answer</li>
        <li><strong>After-hours routing</strong> so no call goes unanswered</li>
        <li><strong>Monthly reporting</strong> showing recovered calls and revenue</li>
      </ul>
    </div>
    <div class="panel">
      <h2>Methodology</h2>
      <ul>
        <li>We placed {result.total_calls} real calls to your business line</li>
        <li>Each call was tracked for answer disposition and ring time</li>
        <li>Revenue estimates use a ${appt_value} average {service} appointment</li>
        <li>Recovery rate of 30% is conservative (industry avg is 35-40%)</li>
      </ul>
    </div>
  </div>

  <div class="footer">
    <div>
      <strong>Next step:</strong> Book a free 15-min demo<br/>
      <span class="mono">https://calendly.com/igorganapolsky/audit-call</span>
    </div>
    <div>
      Email: <span class="mono">hello@callcatcherops.com</span><br/>
      Coral Springs, FL
    </div>
  </div>
</div>
</body>
</html>"""

    slug = result.company.lower().replace(" ", "-")[:30]
    filename = f"audit_{slug}_{as_of}.html"
    path = out_dir / filename
    path.write_text(html, encoding="utf-8")
    return path


def main() -> None:
    """Load a previously saved audit JSON and regenerate the HTML report."""
    import argparse

    p = argparse.ArgumentParser(description="Generate HTML audit report from JSON.")
    p.add_argument("json_file", type=Path, help="Path to audit JSON file")
    p.add_argument("--output", type=Path, default=None, help="Output directory")
    args = p.parse_args()

    data = json.loads(args.json_file.read_text(encoding="utf-8"))

    # Reconstruct a minimal result object.
    from types import SimpleNamespace

    probes = []
    for pd in data.get("probes", []):
        probes.append(SimpleNamespace(**pd))

    result = SimpleNamespace(
        phone=data["phone"],
        company=data["company"],
        service=data["service"],
        state=data.get("state", "FL"),
        audit_date=data["audit_date"],
        probes=probes,
        total_calls=len(probes),
        answered_human=sum(1 for p in probes if p.outcome == "spoke"),
        voicemail=sum(1 for p in probes if p.outcome == "voicemail"),
        no_answer=sum(1 for p in probes if p.outcome == "no_answer"),
        answer_rate_pct=round(sum(1 for p in probes if p.outcome == "spoke") / max(len(probes), 1) * 100, 1),
        miss_rate_pct=round(100 - sum(1 for p in probes if p.outcome == "spoke") / max(len(probes), 1) * 100, 1),
    )

    path = generate_audit_report(result, output_dir=args.output)
    print(f"Report generated: {path}")


if __name__ == "__main__":
    main()
