#!/usr/bin/env python3
"""Missed-call audit: call a business phone at multiple times and log what happens.

Usage:
    python3 -m autonomy.tools.missed_call_audit \
        --phone "+19541234567" \
        --company "Coral Springs Dental" \
        --service dentist \
        --calls 5 \
        --delay 0

The tool places real Twilio calls (silent — hangs up quickly after detecting
the answer disposition) and records each result.  After all calls complete,
it generates a 1-page HTML audit report in autonomy/state/.

Requires: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER in env.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from autonomy.tools.twilio_autocall import (
    create_call,
    load_twilio_config,
    map_twilio_call_to_outcome,
    wait_for_call_terminal_status,
)
from autonomy.utils import UTC, normalize_us_phone, now_utc_iso

STATE_DIR = Path(__file__).resolve().parents[1] / "state"

# Short silent TwiML — lets the call connect, pauses briefly, then hangs up.
# This is enough for Twilio to detect human vs machine and measure ring time.
_AUDIT_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Response><Pause length=\"3\"/><Hangup/></Response>"
)


@dataclass
class CallProbe:
    """Result of a single audit call."""

    attempt: int
    attempted_at: str
    outcome: str  # spoke, voicemail, no_answer, wrong_number, failed
    twilio_status: str
    answered_by: str
    duration_secs: float  # wall-clock time from dial to terminal status
    notes: str


@dataclass
class AuditResult:
    """Full audit result for a business."""

    phone: str
    company: str
    service: str
    state: str
    audit_date: str
    probes: list[CallProbe] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return len(self.probes)

    @property
    def answered_human(self) -> int:
        return sum(1 for p in self.probes if p.outcome == "spoke")

    @property
    def voicemail(self) -> int:
        return sum(1 for p in self.probes if p.outcome == "voicemail")

    @property
    def no_answer(self) -> int:
        return sum(1 for p in self.probes if p.outcome == "no_answer")

    @property
    def answer_rate_pct(self) -> float:
        if not self.probes:
            return 0.0
        return round(self.answered_human / self.total_calls * 100, 1)

    @property
    def miss_rate_pct(self) -> float:
        return round(100.0 - self.answer_rate_pct, 1)

    @property
    def avg_ring_secs(self) -> float:
        durations = [p.duration_secs for p in self.probes if p.duration_secs > 0]
        if not durations:
            return 0.0
        return round(sum(durations) / len(durations), 1)


def run_audit(
    *,
    phone: str,
    company: str,
    service: str,
    state: str,
    num_calls: int,
    delay_between_secs: int,
    env: dict[str, str],
) -> AuditResult:
    """Place num_calls to the target phone and record dispositions."""

    e164 = normalize_us_phone(phone)
    if not e164:
        raise SystemExit(f"Invalid phone number: {phone}")

    # Override TwiML with our silent audit version.
    env = {**env, "AUTO_CALLS_TWIML": _AUDIT_TWIML, "AUTO_CALLS_MACHINE_DETECTION": "1"}
    cfg = load_twilio_config(env)
    if cfg is None:
        raise SystemExit("Missing Twilio credentials (TWILIO_ACCOUNT_SID / AUTH_TOKEN / FROM_NUMBER).")

    result = AuditResult(
        phone=e164,
        company=company,
        service=service,
        state=state,
        audit_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )

    for i in range(num_calls):
        if i > 0 and delay_between_secs > 0:
            print(f"  Waiting {delay_between_secs}s before next call...")
            time.sleep(delay_between_secs)

        attempted_at = now_utc_iso()
        t0 = time.monotonic()
        print(f"  Call {i + 1}/{num_calls} to {e164}...")

        try:
            created = create_call(cfg, to_number=e164)
            call_sid = str(created.get("sid") or "")
            final = wait_for_call_terminal_status(cfg, call_sid=call_sid) if call_sid else created
            outcome, notes = map_twilio_call_to_outcome(final)
        except Exception as exc:
            outcome = "failed"
            notes = str(exc)[:200]
            final = {}

        elapsed = round(time.monotonic() - t0, 1)

        probe = CallProbe(
            attempt=i + 1,
            attempted_at=attempted_at,
            outcome=outcome,
            twilio_status=str(final.get("status") or ""),
            answered_by=str(final.get("answered_by") or ""),
            duration_secs=elapsed,
            notes=notes,
        )
        result.probes.append(probe)
        print(f"    -> {outcome} ({elapsed}s) {notes}")

    return result


def save_audit(result: AuditResult, output_dir: Path | None = None) -> Path:
    """Save audit result as JSON."""
    out_dir = output_dir or STATE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = result.company.lower().replace(" ", "-")[:30]
    filename = f"audit_{slug}_{result.audit_date}.json"
    path = out_dir / filename
    path.write_text(json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run a missed-call audit on a business phone number.")
    p.add_argument("--phone", required=True, help="Business phone number to audit (US format)")
    p.add_argument("--company", required=True, help="Business name")
    p.add_argument("--service", default="dentist", help="Service type (dentist, plumber, hvac, etc.)")
    p.add_argument("--state", default="FL", help="US state abbreviation")
    p.add_argument("--calls", type=int, default=5, help="Number of audit calls to place")
    p.add_argument("--delay", type=int, default=0, help="Seconds between calls (0 for immediate)")
    p.add_argument("--output", type=Path, default=None, help="Output directory for results")
    return p.parse_args()


def main() -> None:
    import os

    args = parse_args()
    env = dict(os.environ)

    print(f"Running missed-call audit for {args.company} ({args.phone})")
    print(f"  Service: {args.service} | State: {args.state} | Calls: {args.calls}")

    result = run_audit(
        phone=args.phone,
        company=args.company,
        service=args.service,
        state=args.state,
        num_calls=args.calls,
        delay_between_secs=args.delay,
        env=env,
    )

    json_path = save_audit(result, args.output)
    print(f"\nAudit complete. Results saved to {json_path}")
    print(f"  Answer rate: {result.answer_rate_pct}% ({result.answered_human}/{result.total_calls})")
    print(f"  Miss rate: {result.miss_rate_pct}%")
    print(f"  Voicemail: {result.voicemail}")
    print(f"  No answer: {result.no_answer}")
    print(f"  Avg ring time: {result.avg_ring_secs}s")

    # Generate HTML report.
    from autonomy.tools.audit_report import generate_audit_report

    html_path = generate_audit_report(result, output_dir=args.output)
    print(f"  HTML report: {html_path}")


if __name__ == "__main__":
    main()
