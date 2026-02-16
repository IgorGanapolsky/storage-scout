from __future__ import annotations

import uuid
from pathlib import Path

from autonomy.context_store import ContextStore, Lead
from autonomy.tools.fastmail_inbox_sync import (
    InboxSyncResult,
    _extract_failed_recipients,
    _is_bounce,
)
from autonomy.tools.live_job import (
    _evaluate_paid_stop_loss,
    _format_report,
    _parse_categories,
)
from autonomy.tools.scoreboard import Scoreboard, load_scoreboard


def _tmp_state_paths(tmp_name: str) -> tuple[str, str]:
    # ContextStore restricts writes under autonomy/state.
    db_path = f"autonomy/state/{tmp_name}.sqlite3"
    audit_path = f"autonomy/state/{tmp_name}.jsonl"
    return db_path, audit_path


def test_context_store_mark_status_by_email_and_scoreboard_counts() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)

    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)

    # Create 4 leads across statuses.
    leads = [
        Lead(id="new@example.com", name="", company="A", email="new@example.com", phone="", service="", city="", state="", source="t"),
        Lead(
            id="contacted@example.com",
            name="",
            company="B",
            email="contacted@example.com",
            phone="",
            service="",
            city="",
            state="",
            source="t",
        ),
        Lead(
            id="replied@example.com",
            name="",
            company="C",
            email="replied@example.com",
            phone="",
            service="",
            city="",
            state="",
            source="t",
        ),
        Lead(
            id="bounced@example.com",
            name="",
            company="D",
            email="bounced@example.com",
            phone="",
            service="",
            city="",
            state="",
            source="t",
        ),
    ]
    for lead in leads:
        store.upsert_lead(lead)

    assert store.mark_status_by_email("contacted@example.com", "contacted") is True
    assert store.mark_status_by_email("replied@example.com", "replied") is True
    assert store.mark_status_by_email("bounced@example.com", "bounced") is True

    # Seed sent messages so scoreboard can compute totals.
    store.add_message(lead_id="contacted@example.com", channel="email", subject="s", body="b", status="sent")
    store.add_message(lead_id="replied@example.com", channel="email", subject="s", body="b", status="sent")

    board = load_scoreboard(Path(sqlite_path), days=30)
    assert board.leads_total == 4
    assert board.leads_new == 1
    assert board.leads_contacted == 1
    assert board.leads_replied == 1
    assert board.leads_bounced == 1
    assert board.leads_other == 0
    assert board.email_sent_total == 2


def test_fastmail_bounce_recipient_extraction_and_bounce_detection() -> None:
    body = (
        "Delivery has failed to these recipients or groups:\n"
        "info@example.com\n\n"
        "Recipient address: sales@example.org\n"
        "Final-Recipient: rfc822; owner@example.net\n"
    )
    recipients = _extract_failed_recipients(body)
    assert "info@example.com" in recipients
    assert "sales@example.org" in recipients
    assert "owner@example.net" in recipients

    assert _is_bounce("Mail Delivery System", "mailer-daemon@example.com", "Undelivered Mail Returned to Sender", body)
    assert _is_bounce("", "postmaster@example.com", "Delivery Status Notification (Failure)", body)


def test_live_job_report_formatting() -> None:
    inbox = InboxSyncResult(
        processed_messages=1,
        new_bounces=0,
        new_replies=0,
        new_opt_outs=0,
        intake_submissions=0,
        calendly_bookings=0,
        stripe_payments=0,
        last_uid=123,
    )
    board = Scoreboard(
        leads_total=10,
        leads_new=2,
        leads_contacted=5,
        leads_replied=1,
        leads_bounced=2,
        leads_other=0,
        email_sent_total=7,
        email_sent_recent=7,
        emailed_leads_recent=7,
        bounced_leads_recent=2,
        bounce_rate_recent=2 / 7,
        opt_out_total=0,
        last_email_ts="2026-02-13T00:00:00+00:00",
        call_attempts_total=0,
        call_attempts_recent=0,
        call_booked_total=0,
        call_booked_recent=0,
        last_call_ts="",
    )
    report = _format_report(
        leadgen_new=0,
        engine_result={"sent_initial": 0, "sent_followup": 0},
        inbox_result=inbox,
        scoreboard=board,
        scoreboard_days=30,
    )
    assert "CallCatcher Ops Daily Report" in report
    assert "Inbox sync (Fastmail)" in report
    assert "Scoreboard (last 30 days)" in report


def test_live_job_report_includes_guardrails_section() -> None:
    inbox = InboxSyncResult(
        processed_messages=0,
        new_bounces=0,
        new_replies=0,
        new_opt_outs=0,
        intake_submissions=0,
        calendly_bookings=0,
        stripe_payments=0,
        last_uid=0,
    )
    board = Scoreboard(
        leads_total=0,
        leads_new=0,
        leads_contacted=0,
        leads_replied=0,
        leads_bounced=0,
        leads_other=0,
        email_sent_total=0,
        email_sent_recent=0,
        emailed_leads_recent=0,
        bounced_leads_recent=0,
        bounce_rate_recent=0.0,
        opt_out_total=0,
        last_email_ts="",
        call_attempts_total=0,
        call_attempts_recent=0,
        call_booked_total=0,
        call_booked_recent=0,
        last_call_ts="",
    )
    report = _format_report(
        leadgen_new=0,
        engine_result={"sent_initial": 0, "sent_followup": 0},
        inbox_result=inbox,
        scoreboard=board,
        scoreboard_days=30,
        guardrails={"deliverability_blocked": True, "stop_loss_blocked": True},
    )
    assert "Guardrails" in report
    assert "- deliverability_blocked: True" in report
    assert "- stop_loss_blocked: True" in report


def test_stop_loss_blocks_and_resets(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "autonomy" / "state").mkdir(parents=True, exist_ok=True)
    env = {
        "STOP_LOSS_ENABLED": "1",
        "STOP_LOSS_ZERO_REVENUE_RUNS": "1",
        "STOP_LOSS_ZERO_REVENUE_DAYS": "7",
    }

    blocked = _evaluate_paid_stop_loss(repo_root=repo_root, env=env, has_revenue_signal=False)
    assert blocked["blocked"] is True
    assert blocked["block_reason"] == "stop_loss_zero_revenue_runs"

    reset = _evaluate_paid_stop_loss(repo_root=repo_root, env=env, has_revenue_signal=True)
    assert reset["blocked"] is False
    assert int(reset["zero_revenue_runs"]) == 0


def test_leadgen_category_parsing() -> None:
    assert _parse_categories("") == []
    assert _parse_categories("  med spa, plumbing ,, Clinics  ") == ["med spa", "plumbing", "clinics"]
