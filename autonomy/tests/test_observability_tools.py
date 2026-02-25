from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from autonomy.context_store import ContextStore, Lead
from autonomy.tools.fastmail_inbox_sync import (
    InboxSyncResult,
    _extract_failed_recipients,
    _is_bounce,
    _looks_like_calendly_booking,
    _looks_like_stripe_payment,
)
from autonomy.tools.live_job import (
    _filter_call_list_rows_for_hygiene,
    _maybe_write_call_list,
    _compute_sms_channel_budgets,
    _count_actions_today,
    _evaluate_paid_stop_loss,
    _format_report,
    _parse_categories,
)
from autonomy.tools.call_list import CallListRow
from autonomy.tools.scoreboard import Scoreboard, load_scoreboard
from autonomy.tools.twilio_tollfree_watchdog import TwilioTollfreeWatchdogResult


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
    store.log_action(
        agent_id="agent.inbox_sync.v1",
        action_type="conversion.booking",
        trace_id="imap:booking:test1",
        payload={"source": "fastmail"},
    )
    store.log_action(
        agent_id="agent.inbox_sync.v1",
        action_type="conversion.payment",
        trace_id="imap:payment:test1",
        payload={"source": "fastmail"},
    )

    board = load_scoreboard(Path(sqlite_path), days=30)
    assert board.leads_total == 4
    assert board.leads_new == 1
    assert board.leads_contacted == 1
    assert board.leads_replied == 1
    assert board.leads_bounced == 1
    assert board.leads_other == 0
    assert board.email_sent_total == 2
    assert board.bookings_total == 1
    assert board.stripe_payments_total == 1


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


def test_fastmail_booking_and_payment_detection_heuristics() -> None:
    assert _looks_like_calendly_booking(
        "notifications@calendly.com",
        "Invitation: Intro Call",
        "You are scheduled. https://calendly.com/example/team",
    )
    assert _looks_like_calendly_booking(
        "no-reply@example.com",
        "You are scheduled with CallCatcher Ops",
        "",
    )
    assert _looks_like_stripe_payment(
        "receipts+acct@example.com",
        "Your payment receipt",
        "checkout.stripe.com/pay/cs_test_123",
    )
    assert _looks_like_stripe_payment(
        "support@stripe.com",
        "Invoice paid",
        "",
    )


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
        calendly_bookings_total=0,
        calendly_bookings_recent=0,
        stripe_payments_total=0,
        stripe_payments_recent=0,
        bookings_total=0,
        bookings_recent=0,
        last_call_ts="",
    )
    report = _format_report(
        leadgen_new=0,
        lead_hygiene={
            "reason": "ok",
            "enabled": True,
            "total": 12,
            "invalid": 2,
            "skipped": 0,
            "call_list_removed": 1,
            "daily_report_path": "autonomy/state/lead_hygiene_removal_2026-02-24.json",
            "latest_report_path": "autonomy/state/lead_hygiene_removal_latest.json",
        },
        engine_result={"sent_initial": 0, "sent_followup": 0},
        inbox_result=inbox,
        scoreboard=board,
        scoreboard_days=30,
        kpi={"bookings_today": 0, "payments_today": 0, "bookings_window": 0, "payments_window": 0},
    )
    assert "CallCatcher Ops Daily Report" in report
    assert "Lead hygiene" in report
    assert "- invalid_marked: 2" in report
    assert "Revenue KPI" in report
    assert "Inbox sync (Fastmail)" in report
    assert "Scoreboard (last 30 days)" in report


def test_filter_call_list_rows_for_hygiene_removes_bad_rows() -> None:
    rows = [
        CallListRow(
            company="Good Co",
            service="dentist",
            city="Fort Lauderdale",
            state="FL",
            phone="+1 (954) 555-1212",
            website="",
            contact_name="",
            email="owner@goodco.com",
            email_method="direct",
            lead_status="new",
            score=92,
            source="test",
            role_inbox="no",
            last_email_ts="",
            email_sent_count=0,
            opted_out="no",
        ),
        CallListRow(
            company="Artifact LLC",
            service="dentist",
            city="Fort Lauderdale",
            state="FL",
            phone="+1 (954) 555-1213",
            website="",
            contact_name="",
            email="asset@3x.png",
            email_method="scrape",
            lead_status="new",
            score=88,
            source="test",
            role_inbox="no",
            last_email_ts="",
            email_sent_count=0,
            opted_out="no",
        ),
        CallListRow(
            company="No Phone Inc",
            service="dentist",
            city="Fort Lauderdale",
            state="FL",
            phone="N/A",
            website="",
            contact_name="",
            email="owner@nophone.com",
            email_method="direct",
            lead_status="contacted",
            score=85,
            source="test",
            role_inbox="no",
            last_email_ts="",
            email_sent_count=0,
            opted_out="no",
        ),
    ]

    kept, summary = _filter_call_list_rows_for_hygiene(rows=rows, enabled=True, sample_limit=10)
    assert len(kept) == 1
    assert int(summary["removed_count"]) == 2
    reason_counts = dict(summary["reason_counts"])
    assert int(reason_counts["email_junk_artifact"]) == 1
    assert int(reason_counts["bad_phone"]) == 1
    samples = list(summary["samples"])
    assert len(samples) == 2
    assert all("email_sha256" in s for s in samples)
    assert all("@" not in str(s) for s in samples)


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
        calendly_bookings_total=0,
        calendly_bookings_recent=0,
        stripe_payments_total=0,
        stripe_payments_recent=0,
        bookings_total=0,
        bookings_recent=0,
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


def test_live_job_report_includes_twilio_tollfree_section() -> None:
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
        calendly_bookings_total=0,
        calendly_bookings_recent=0,
        stripe_payments_total=0,
        stripe_payments_recent=0,
        bookings_total=0,
        bookings_recent=0,
        last_call_ts="",
    )
    report = _format_report(
        leadgen_new=0,
        engine_result={"sent_initial": 0, "sent_followup": 0},
        inbox_result=inbox,
        scoreboard=board,
        scoreboard_days=30,
        twilio_tollfree=TwilioTollfreeWatchdogResult(
            reason="auto_fix_applied",
            status="IN_REVIEW",
            verification_sid="HH123",
            auto_fix_attempted=True,
            auto_fix_applied=True,
            should_alert=False,
            alert_reason="",
        ),
    )
    assert "Twilio toll-free verification" in report
    assert "- status: IN_REVIEW" in report
    assert "- auto_fix_applied: True" in report


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


def test_stop_loss_is_idempotent_same_day_and_clamps_legacy_runs(tmp_path: Path) -> None:
    repo_root = tmp_path
    state_dir = repo_root / "autonomy" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date()

    # Simulate pre-fix inflated state from repeated same-day scheduler invocations.
    (state_dir / "paid_stop_loss_state.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "has_revenue_signal": False,
                "zero_revenue_runs": 150,
                "zero_revenue_days": 6,
                "first_zero_revenue_date_utc": (today - timedelta(days=5)).isoformat(),
                "last_eval_date_utc": today.isoformat(),
                "blocked": True,
                "block_reason": "stop_loss_zero_revenue_runs",
                "max_zero_runs": 20,
                "max_zero_days": 14,
            }
        ),
        encoding="utf-8",
    )

    env = {
        "STOP_LOSS_ENABLED": "1",
        "STOP_LOSS_ZERO_REVENUE_RUNS": "20",
        "STOP_LOSS_ZERO_REVENUE_DAYS": "14",
    }

    eval_1 = _evaluate_paid_stop_loss(repo_root=repo_root, env=env, has_revenue_signal=False)
    assert int(eval_1["zero_revenue_days"]) == 6
    assert int(eval_1["zero_revenue_runs"]) == 6
    assert eval_1["blocked"] is False

    # Re-evaluation the same day should not increment runs.
    eval_2 = _evaluate_paid_stop_loss(repo_root=repo_root, env=env, has_revenue_signal=False)
    assert int(eval_2["zero_revenue_runs"]) == 6
    assert int(eval_2["zero_revenue_days"]) == 6
    assert eval_2["blocked"] is False


def test_leadgen_category_parsing() -> None:
    assert _parse_categories("") == []
    assert _parse_categories("  med spa, plumbing ,, Clinics  ") == ["med spa", "plumbing", "clinics"]


def test_count_actions_today_paid_scope_filters_non_billable() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)

    # Non-Twilio/manual style call action should not count as billable.
    store.log_action(
        agent_id="agent.manual",
        action_type="call.attempt",
        trace_id="manual-call",
        payload={"lead_id": "a@example.com", "outcome": "spoke"},
    )
    # Twilio call with SID should count as billable.
    store.log_action(
        agent_id="agent.autocall.twilio.v1",
        action_type="call.attempt",
        trace_id="twilio-call",
        payload={"lead_id": "b@example.com", "twilio": {"sid": "CA123"}},
    )
    # Twilio SMS with SID should count as billable.
    store.log_action(
        agent_id="agent.sms.twilio.v1",
        action_type="sms.attempt",
        trace_id="twilio-sms",
        payload={"lead_id": "c@example.com", "twilio": {"sid": "SM123"}},
    )
    # Twilio interest nudge with SID should count as billable SMS scope too.
    store.log_action(
        agent_id="agent.sms.twilio.nudge.v1",
        action_type="sms.interest_nudge",
        trace_id="twilio-sms-nudge",
        payload={"lead_id": "d@example.com", "twilio": {"sid": "SM124"}},
    )

    assert _count_actions_today(store, action_type="call.attempt") == 2
    assert _count_actions_today(store, action_type="call.attempt", paid_only=True) == 1
    assert _count_actions_today(store, action_type="sms.attempt", paid_only=True) == 1
    assert _count_actions_today(store, action_type="sms.interest_nudge", paid_only=True) == 1


def test_compute_sms_channel_budgets_holds_interest_reserve() -> None:
    budgets = _compute_sms_channel_budgets(
        daily_sms_cap=10,
        sms_today_followup=6,
        sms_today_nudge=0,
        interest_reserve=3,
    )
    assert budgets["total_remaining"] == 4
    assert budgets["interest_reserve"] == 3
    assert budgets["interest_reserve_remaining"] == 3
    assert budgets["followup_remaining"] == 1


def test_compute_sms_channel_budgets_releases_reserve_after_nudges() -> None:
    budgets = _compute_sms_channel_budgets(
        daily_sms_cap=10,
        sms_today_followup=6,
        sms_today_nudge=2,
        interest_reserve=3,
    )
    assert budgets["total_remaining"] == 2
    assert budgets["interest_reserve_remaining"] == 1
    assert budgets["followup_remaining"] == 1

    budgets2 = _compute_sms_channel_budgets(
        daily_sms_cap=10,
        sms_today_followup=6,
        sms_today_nudge=3,
        interest_reserve=3,
    )
    assert budgets2["total_remaining"] == 1
    assert budgets2["interest_reserve_remaining"] == 0
    assert budgets2["followup_remaining"] == 1


def test_maybe_write_call_list_high_intent_sanitizes_bounced_and_score_floor(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "autonomy" / "state").mkdir(parents=True, exist_ok=True)

    cfg = SimpleNamespace(
        lead_sources=[{"type": "csv", "path": "autonomy/state/leads_callcatcherops_real.csv"}],
        agents={"outreach": {"target_services": ["Dentist"]}},
        storage={"sqlite_path": "autonomy/state/autonomy_live.sqlite3"},
    )

    captured: dict[str, object] = {}

    def fake_generate_call_list(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return []

    monkeypatch.setattr("autonomy.tools.live_job.generate_call_list", fake_generate_call_list)
    monkeypatch.setattr("autonomy.tools.live_job.write_call_list", lambda *_args, **_kwargs: None)

    out = _maybe_write_call_list(
        cfg=cfg,
        env={
            "HIGH_INTENT_OUTREACH_ONLY": "1",
            "DAILY_CALL_LIST_SERVICES": "Dentist",
            "DAILY_CALL_LIST_STATUSES": "replied,contacted,new,bounced",
            "DAILY_CALL_LIST_MIN_SCORE": "60",
            "DAILY_CALL_LIST_LIMIT": "10",
        },
        repo_root=repo_root,
    )
    assert out is not None
    assert out["statuses"] == ["replied", "contacted", "new"]
    assert int(out["min_score"] or 0) == 70
    assert bool(out["enrichment_enabled"]) is True
    assert int(out["call_signal_days"] or 0) == 14
    assert int(out["sms_signal_days"] or 0) == 30
    assert captured["statuses"] == ["replied", "contacted", "new"]
    assert int(captured["min_score"] or 0) == 70
    assert bool(captured["enrichment_enabled"]) is True
    assert int(captured["call_signal_days"] or 0) == 14
    assert int(captured["sms_signal_days"] or 0) == 30
