from __future__ import annotations

import json
import os
import sys
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
    _apply_edit_mode_config_overrides,
    _apply_edit_mode_env_overrides,
    _apply_outreach_runtime_policy,
    _check_approval_gate,
    _collect_sms_channel_state,
    _should_block_deliverability,
    _filter_call_list_rows_for_hygiene,
    _maybe_write_call_list,
    _compute_sms_channel_budgets,
    _count_actions_today,
    _evaluate_paid_stop_loss,
    _format_report,
    _parse_categories,
    _resolve_config_path,
    _resolve_paid_sms_block_reason,
    _run_interest_nudges_with_budget,
    _run_warm_close_with_budget,
    main as live_job_main,
)
from autonomy.tools.call_list import CallListRow
from autonomy.tools.scoreboard import Scoreboard, load_scoreboard
from autonomy.tools.twilio_inbox_sync import TwilioInboxResult
from autonomy.tools.twilio_interest_nudge import InterestNudgeResult
from autonomy.tools.twilio_tollfree_watchdog import TwilioTollfreeWatchdogResult
from autonomy.tools.twilio_warm_close import WarmCloseResult


def _tmp_state_paths(tmp_name: str) -> tuple[str, str]:
    # ContextStore restricts writes under autonomy/state.
    db_path = f"autonomy/state/{tmp_name}.sqlite3"
    audit_path = f"autonomy/state/{tmp_name}.jsonl"
    return db_path, audit_path


def _zero_board() -> Scoreboard:
    return Scoreboard(
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
    store.close()


def test_context_store_close_is_idempotent() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)
    store.close()
    store.close()


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
        "You are scheduled with AEO Autopilot",
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
    assert "AEO Autopilot Daily Report" in report
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


def test_live_job_report_includes_warm_close_section() -> None:
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
        warm_close=WarmCloseResult(
            reason="ok",
            candidates=2,
            attempted=2,
            sent=1,
            failed=1,
            skipped=0,
            converted_skipped=0,
        ),
    )
    assert "Warm lead close loop (Twilio)" in report
    assert "- sent: 1" in report


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


def test_edit_mode_env_overrides_apply_as_strings() -> None:
    env = {"AUTO_CALLS_ENABLED": "0", "PAID_DAILY_CALL_CAP": "0"}
    payload = {"env": {"AUTO_CALLS_ENABLED": 1, "PAID_DAILY_CALL_CAP": 12, "NEW_FLAG": True}}
    applied = _apply_edit_mode_env_overrides(env=env, payload=payload)
    assert applied == 3
    assert env["AUTO_CALLS_ENABLED"] == "1"
    assert env["PAID_DAILY_CALL_CAP"] == "12"
    assert env["NEW_FLAG"] == "True"


def test_edit_mode_config_overrides_deep_merge_without_dropping_defaults() -> None:
    cfg = SimpleNamespace(
        mode="live",
        company={"name": "AEO Autopilot", "booking_url": "https://cal.example.com/original"},
        agents={"outreach": {"daily_send_limit": 25, "followup": {"enabled": True, "daily_send_limit": 15}}},
        lead_sources=[{"type": "csv", "path": "autonomy/state/leads_ai_seo_real.csv", "source": "ai-seo"}],
        email={"smtp_user": "hello@aiseoautopilot.com"},
        compliance={"unsubscribe_url": "https://aiseoautopilot.com/unsubscribe.html?email={{email}}"},
        storage={"sqlite_path": "autonomy/state/autonomy_live.sqlite3", "audit_log": "autonomy/state/audit_live.jsonl"},
    )
    payload = {
        "config": {
            "company": {"booking_url": "https://cal.example.com/ai-seo"},
            "agents": {"outreach": {"daily_send_limit": 10, "followup": {"daily_send_limit": 5}}},
        }
    }

    applied = _apply_edit_mode_config_overrides(cfg=cfg, payload=payload)
    assert applied == 2
    assert cfg.company["name"] == "AEO Autopilot"
    assert cfg.company["booking_url"] == "https://cal.example.com/ai-seo"
    outreach = dict(cfg.agents["outreach"])
    assert int(outreach["daily_send_limit"]) == 10
    assert bool(outreach["followup"]["enabled"]) is True
    assert int(outreach["followup"]["daily_send_limit"]) == 5


def test_approval_gate_blocks_without_grant_and_allows_with_grant() -> None:
    blocked, reason = _check_approval_gate(
        action="calls.twilio",
        env={
            "APPROVAL_GATE_ENABLED": "1",
            "APPROVAL_REQUIRED_ACTIONS": "calls.twilio,sms.twilio",
            "APPROVAL_GRANTS": "",
        },
    )
    assert blocked is False
    assert reason == "approval_required"

    allowed, reason2 = _check_approval_gate(
        action="calls.twilio",
        env={
            "APPROVAL_GATE_ENABLED": "1",
            "APPROVAL_REQUIRED_ACTIONS": "calls.twilio,sms.twilio",
            "APPROVAL_GRANTS": "calls.twilio",
        },
    )
    assert allowed is True
    assert reason2 == ""


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
    # Twilio warm-close SMS with SID should count as billable too.
    store.log_action(
        agent_id="agent.sms.twilio.warm_close.v1",
        action_type="sms.warm_close",
        trace_id="twilio-sms-warm-close",
        payload={"lead_id": "e@example.com", "twilio": {"sid": "SM125"}},
    )

    assert _count_actions_today(store, action_type="call.attempt") == 2
    assert _count_actions_today(store, action_type="call.attempt", paid_only=True) == 1
    assert _count_actions_today(store, action_type="sms.attempt", paid_only=True) == 1
    assert _count_actions_today(store, action_type="sms.interest_nudge", paid_only=True) == 1
    assert _count_actions_today(store, action_type="sms.warm_close", paid_only=True) == 1
    store.close()


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


def test_compute_sms_channel_budgets_holds_warm_close_reserve() -> None:
    budgets = _compute_sms_channel_budgets(
        daily_sms_cap=10,
        sms_today_followup=6,
        sms_today_nudge=1,
        sms_today_warm_close=0,
        interest_reserve=2,
        warm_close_reserve=2,
    )
    assert budgets["total_remaining"] == 3
    assert budgets["warm_close_reserve_remaining"] == 2
    assert budgets["interest_reserve_remaining"] == 1
    assert budgets["warm_close_remaining"] == 2
    assert budgets["nudge_remaining"] == 1
    assert budgets["followup_remaining"] == 0


def test_collect_sms_channel_state_populates_paid_scoped_guardrails() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)
    store.log_action(
        agent_id="agent.manual",
        action_type="sms.attempt",
        trace_id="manual-sms",
        payload={"lead_id": "manual@example.com"},
    )
    store.log_action(
        agent_id="agent.sms.twilio.v1",
        action_type="sms.attempt",
        trace_id="twilio-sms",
        payload={"lead_id": "a@example.com", "twilio": {"sid": "SM001"}},
    )
    store.log_action(
        agent_id="agent.sms.twilio.nudge.v1",
        action_type="sms.interest_nudge",
        trace_id="twilio-nudge",
        payload={"lead_id": "b@example.com", "twilio": {"sid": "SM002"}},
    )
    store.log_action(
        agent_id="agent.sms.twilio.warm_close.v1",
        action_type="sms.warm_close",
        trace_id="twilio-warm-close",
        payload={"lead_id": "c@example.com", "twilio": {"sid": "SM003"}},
    )

    guardrails: dict[str, object] = {}
    state = _collect_sms_channel_state(
        store=store,
        env={
            "PAID_DAILY_SMS_CAP": "8",
            "PAID_DAILY_SMS_INTEREST_RESERVE": "2",
            "PAID_DAILY_SMS_WARM_CLOSE_RESERVE": "2",
        },
        guardrails=guardrails,
    )
    store.close()

    assert state["daily_sms_cap"] == 8
    assert state["sms_today_all"] == 4
    assert state["sms_today"] == 3
    assert state["sms_warm_close_budget_remaining"] == 4
    assert state["sms_nudge_budget_remaining"] == 4
    assert state["sms_followup_budget_remaining"] == 3
    assert int(guardrails["sms_daily_cap"]) == 8
    assert int(guardrails["sms_today_warm_close_actions"]) == 1
    assert int(guardrails["sms_today_interest_nudges"]) == 1
    assert int(guardrails["sms_budget_remaining"]) == 5


def test_resolve_paid_sms_block_reason_precedence() -> None:
    assert _resolve_paid_sms_block_reason(
        env={"AUTO_WARM_CLOSE_ENABLED": "0"},
        enabled_env_key="AUTO_WARM_CLOSE_ENABLED",
        disabled_reason="disabled_channel",
        approval_action="sms.warm_close",
        paid_kill_switch=False,
        stop_loss_state={"blocked": False},
        budget_remaining=2,
        exhausted_reason="budget_exhausted",
    ) == "disabled_channel"

    assert _resolve_paid_sms_block_reason(
        env={
            "AUTO_WARM_CLOSE_ENABLED": "1",
            "APPROVAL_GATE_ENABLED": "1",
            "APPROVAL_REQUIRED_ACTIONS": "sms.warm_close",
            "APPROVAL_GRANTS": "",
        },
        enabled_env_key="AUTO_WARM_CLOSE_ENABLED",
        disabled_reason="disabled_channel",
        approval_action="sms.warm_close",
        paid_kill_switch=False,
        stop_loss_state={"blocked": False},
        budget_remaining=2,
        exhausted_reason="budget_exhausted",
    ) == "approval_required"

    assert _resolve_paid_sms_block_reason(
        env={"AUTO_WARM_CLOSE_ENABLED": "1"},
        enabled_env_key="AUTO_WARM_CLOSE_ENABLED",
        disabled_reason="disabled_channel",
        approval_action="sms.warm_close",
        paid_kill_switch=True,
        stop_loss_state={"blocked": False},
        budget_remaining=2,
        exhausted_reason="budget_exhausted",
    ) == "paid_kill_switch"

    assert _resolve_paid_sms_block_reason(
        env={"AUTO_WARM_CLOSE_ENABLED": "1"},
        enabled_env_key="AUTO_WARM_CLOSE_ENABLED",
        disabled_reason="disabled_channel",
        approval_action="sms.warm_close",
        paid_kill_switch=False,
        stop_loss_state={"blocked": True, "block_reason": "stop_loss_zero_revenue_runs"},
        budget_remaining=2,
        exhausted_reason="budget_exhausted",
    ) == "stop_loss_zero_revenue_runs"

    assert _resolve_paid_sms_block_reason(
        env={"AUTO_WARM_CLOSE_ENABLED": "1"},
        enabled_env_key="AUTO_WARM_CLOSE_ENABLED",
        disabled_reason="disabled_channel",
        approval_action="sms.warm_close",
        paid_kill_switch=False,
        stop_loss_state={"blocked": False},
        budget_remaining=0,
        exhausted_reason="budget_exhausted",
    ) == "budget_exhausted"

    assert _resolve_paid_sms_block_reason(
        env={"AUTO_WARM_CLOSE_ENABLED": "1"},
        enabled_env_key="AUTO_WARM_CLOSE_ENABLED",
        disabled_reason="disabled_channel",
        approval_action="sms.warm_close",
        paid_kill_switch=False,
        stop_loss_state={"blocked": False},
        budget_remaining=1,
        exhausted_reason="budget_exhausted",
    ) == ""


def test_run_warm_close_with_budget_caps_and_recomputes(monkeypatch) -> None:
    captured_env: dict[str, str] = {}

    def fake_run_warm_close_loop(**kwargs):  # noqa: ANN003
        captured_env.update(dict(kwargs["env"]))
        return WarmCloseResult(reason="ok", candidates=1, attempted=1, sent=1, failed=0, skipped=0, converted_skipped=0)

    monkeypatch.setattr("autonomy.tools.live_job.run_warm_close_loop", fake_run_warm_close_loop)

    result, updates = _run_warm_close_with_budget(
        env={"AUTO_WARM_CLOSE_MAX_PER_RUN": "9"},
        sqlite_path=Path("autonomy/state/test.sqlite3"),
        audit_log=Path("autonomy/state/test.jsonl"),
        booking_url="https://cal.example.com/audit",
        kickoff_url="https://pay.example.com/kickoff",
        daily_sms_cap=10,
        sms_today_followup=2,
        sms_today_nudge=1,
        sms_today_warm_close=1,
        daily_sms_interest_reserve=2,
        daily_sms_warm_close_reserve=2,
        sms_warm_close_budget_remaining=2,
    )

    assert captured_env["AUTO_WARM_CLOSE_MAX_PER_RUN"] == "2"
    assert result.sent == 1
    assert updates["sms_budget_remaining"] == 5
    assert updates["sms_warm_close_budget_remaining"] == 4
    assert updates["sms_nudge_budget_remaining"] == 5
    assert updates["sms_followup_budget_remaining"] == 4


def test_run_interest_nudges_with_budget_caps_and_recomputes(monkeypatch) -> None:
    captured_env: dict[str, str] = {}

    def fake_run_interest_nudges(**kwargs):  # noqa: ANN003
        captured_env.update(dict(kwargs["env"]))
        return InterestNudgeResult(reason="ok", candidates=2, attempted=2, nudged=2, failed=0, skipped=0)

    monkeypatch.setattr("autonomy.tools.live_job.run_interest_nudges", fake_run_interest_nudges)

    result, updates = _run_interest_nudges_with_budget(
        env={"AUTO_INTEREST_NUDGE_MAX_PER_RUN": "9"},
        sqlite_path=Path("autonomy/state/test.sqlite3"),
        audit_log=Path("autonomy/state/test.jsonl"),
        booking_url="https://cal.example.com/audit",
        kickoff_url="https://pay.example.com/kickoff",
        daily_sms_cap=10,
        sms_today_followup=2,
        sms_today_nudge=1,
        sms_today_warm_close=1,
        warm_close_sent=1,
        daily_sms_interest_reserve=2,
        daily_sms_warm_close_reserve=2,
        sms_nudge_budget_remaining=3,
    )

    assert captured_env["AUTO_INTEREST_NUDGE_MAX_PER_RUN"] == "3"
    assert result.nudged == 2
    assert updates["sms_budget_remaining"] == 3
    assert updates["sms_nudge_budget_remaining"] == 3
    assert updates["sms_followup_budget_remaining"] == 3


def test_should_block_deliverability_trips_at_threshold() -> None:
    assert (
        _should_block_deliverability(
            gate_enabled=True,
            emailed=10,
            bounce_rate=0.05,
            min_emailed=10,
            max_bounce_rate=0.05,
        )
        is True
    )
    assert (
        _should_block_deliverability(
            gate_enabled=True,
            emailed=9,
            bounce_rate=0.20,
            min_emailed=10,
            max_bounce_rate=0.05,
        )
        is False
    )


def test_apply_outreach_runtime_policy_pauses_email_only_on_deliverability_block() -> None:
    cfg = SimpleNamespace(
        agents={
            "outreach": {
                "min_score": 60,
                "daily_send_limit": 30,
                "followup": {"enabled": True, "daily_send_limit": 15},
            }
        }
    )
    guardrails: dict[str, object] = {}

    _apply_outreach_runtime_policy(
        cfg=cfg,
        env={},
        high_intent_only=False,
        deliverability_block=True,
        guardrails=guardrails,
    )

    outreach_cfg = dict(cfg.agents["outreach"])
    follow_cfg = dict(outreach_cfg["followup"])
    assert int(outreach_cfg["daily_send_limit"]) == 0
    assert bool(follow_cfg["enabled"]) is False
    assert int(follow_cfg["daily_send_limit"]) == 0
    assert bool(guardrails["deliverability_email_paused_only"]) is True


def test_apply_outreach_runtime_policy_respects_high_intent_controls() -> None:
    cfg = SimpleNamespace(
        agents={
            "outreach": {
                "min_score": 75,
                "daily_send_limit": 30,
                "followup": {"enabled": True, "daily_send_limit": 15},
            }
        }
    )
    guardrails: dict[str, object] = {}

    _apply_outreach_runtime_policy(
        cfg=cfg,
        env={"HIGH_INTENT_EMAIL_MIN_SCORE": "80", "HIGH_INTENT_SKIP_COLD_EMAIL": "1"},
        high_intent_only=True,
        deliverability_block=False,
        guardrails=guardrails,
    )

    outreach_cfg = dict(cfg.agents["outreach"])
    assert int(outreach_cfg["min_score"]) == 80
    assert int(outreach_cfg["daily_send_limit"]) == 0
    assert bool(guardrails["high_intent_skip_cold_email"]) is True
    assert bool(guardrails["deliverability_email_paused_only"]) is False


def test_maybe_write_call_list_high_intent_sanitizes_bounced_and_score_floor(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "autonomy" / "state").mkdir(parents=True, exist_ok=True)

    cfg = SimpleNamespace(
        lead_sources=[{"type": "csv", "path": "autonomy/state/leads_ai_seo_real.csv"}],
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


def test_live_job_main_handles_inbox_sync_failure_and_deliverability_block(monkeypatch) -> None:
    run_id = uuid.uuid4().hex
    sqlite_path, audit_log = _tmp_state_paths(f"live_job_main_{run_id}")
    report_rel = f"autonomy/state/live_job_report_{run_id}.txt"
    report_path = Path(report_rel)

    cfg = SimpleNamespace(
        company={
            "name": "AEO Autopilot",
            "booking_url": "https://cal.example.com/audit",
            "kickoff_url": "https://pay.example.com/kickoff",
            "intake_url": "https://example.com/intake",
        },
        compliance={"unsubscribe_url": "https://example.com/unsubscribe?email={{email}}"},
        agents={"outreach": {"daily_send_limit": 1, "followup": {"enabled": True, "daily_send_limit": 1}}},
        lead_sources=[],
        email={"smtp_user": "agent@example.com"},
        storage={"sqlite_path": sqlite_path, "audit_log": audit_log},
    )
    smtp_secret_key = "SMTP_" + "PASS" + "WORD"
    env = {
        "FASTMAIL_USER": "agent@example.com",
        smtp_secret_key: "pw",
        "REPORT_DELIVERY": "none",
        "LIVE_JOB_LOCK": "0",
        "TWILIO_INBOX_SYNC_ENABLED": "1",
        "TWILIO_TOLLFREE_WATCHDOG_ENABLED": "1",
        "FUNNEL_WATCHDOG": "0",
        "AUTO_WARM_CLOSE_ENABLED": "0",
        "AUTO_INTEREST_NUDGE_ENABLED": "0",
    }

    def _raise_inbox(**_kwargs):  # noqa: ANN003
        raise RuntimeError("imap unavailable")

    class _FakeEngine:
        def __init__(self, _cfg) -> None:  # noqa: ANN001
            pass

        def run(self) -> dict[str, int]:
            return {"sent_initial": 0, "sent_followup": 0}

    monkeypatch.setattr("autonomy.tools.live_job.load_dotenv", lambda _path: dict(env))
    monkeypatch.setattr("autonomy.tools.live_job.load_config", lambda _path: cfg)
    monkeypatch.setattr("autonomy.tools.live_job.sync_fastmail_inbox", _raise_inbox)
    monkeypatch.setattr(
        "autonomy.tools.live_job.run_twilio_inbox_sync",
        lambda **_kwargs: TwilioInboxResult(reason="ok", interested=0),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job.run_twilio_tollfree_watchdog",
        lambda **_kwargs: TwilioTollfreeWatchdogResult(
            reason="ok",
            status="IN_REVIEW",
            should_alert=True,
            alert_reason="stale_review",
        ),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._run_autonomous_lead_hygiene",
        lambda **_kwargs: {"enabled": True, "reason": "ok", "total": 0, "invalid": 0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._deliverability_snapshot",
        lambda *_args, **_kwargs: {"window_days": 7, "emailed": 12, "bounced": 2, "bounce_rate": 0.2},
    )
    monkeypatch.setattr("autonomy.tools.live_job.Engine", _FakeEngine)
    monkeypatch.setattr(
        "autonomy.tools.live_job._evaluate_paid_stop_loss",
        lambda **_kwargs: {"blocked": False, "block_reason": "", "zero_revenue_runs": 0, "zero_revenue_days": 0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._collect_sms_channel_state",
        lambda **_kwargs: {
            "daily_sms_cap": 10,
            "daily_sms_interest_reserve": 2,
            "daily_sms_warm_close_reserve": 2,
            "sms_today_all": 0,
            "sms_today": 0,
            "sms_today_followup": 0,
            "sms_today_nudge": 0,
            "sms_today_warm_close": 0,
            "sms_budget_remaining": 10,
            "sms_warm_close_budget_remaining": 0,
            "sms_nudge_budget_remaining": 0,
            "sms_followup_budget_remaining": 0,
        },
    )
    monkeypatch.setattr("autonomy.tools.live_job._maybe_write_call_list", lambda **_kwargs: None)
    monkeypatch.setattr(
        "autonomy.tools.live_job._write_lead_hygiene_daily_report",
        lambda **_kwargs: {"daily_report_path": "", "latest_report_path": ""},
    )
    monkeypatch.setattr("autonomy.tools.live_job.load_scoreboard", lambda *_args, **_kwargs: _zero_board())
    monkeypatch.setattr(
        "autonomy.tools.live_job.build_revenue_lesson",
        lambda **_kwargs: SimpleNamespace(
            bottleneck="none",
            leading_signal="none",
            confidence_pct=100,
            next_actions=["keep running"],
        ),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job.record_revenue_lesson",
        lambda **_kwargs: {"saved": True, "path": "autonomy/state/revenue_learning.jsonl"},
    )
    monkeypatch.setattr("autonomy.tools.live_job._format_report", lambda **_kwargs: "daily report")
    monkeypatch.setattr("autonomy.tools.generate_dashboard.generate", lambda: None)

    monkeypatch.setattr(
        sys,
        "argv",
        ["live_job.py", "--config", "autonomy/state/config.ai-seo.live.json", "--report-path", report_rel],
    )
    live_job_main()
    assert report_path.exists()
    report_path.unlink(missing_ok=True)


def test_resolve_config_path_default_live_missing_exits(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "autonomy" / "state").mkdir(parents=True, exist_ok=True)

    try:
        _resolve_config_path(repo_root=repo_root, config_arg="autonomy/state/config.ai-seo.live.json")
        assert False, "expected SystemExit for missing default live config"
    except SystemExit as exc:
        assert "Missing required live config" in str(exc)


def test_live_job_main_allows_no_fastmail_creds_when_sync_disabled_and_report_none(monkeypatch) -> None:
    run_id = uuid.uuid4().hex
    sqlite_path, audit_log = _tmp_state_paths(f"live_job_main_no_fastmail_{run_id}")
    report_rel = f"autonomy/state/live_job_report_no_fastmail_{run_id}.txt"
    report_path = Path(report_rel)

    cfg = SimpleNamespace(
        company={
            "name": "AEO Autopilot",
            "booking_url": "https://cal.example.com/audit",
            "kickoff_url": "https://pay.example.com/kickoff",
            "intake_url": "https://example.com/intake",
        },
        compliance={"unsubscribe_url": "https://example.com/unsubscribe?email={{email}}"},
        agents={"outreach": {"daily_send_limit": 1, "followup": {"enabled": True, "daily_send_limit": 1}}},
        lead_sources=[],
        email={"smtp_user": "agent@example.com"},
        storage={"sqlite_path": sqlite_path, "audit_log": audit_log},
    )
    env = {
        "REPORT_DELIVERY": "none",
        "FASTMAIL_INBOX_SYNC_ENABLED": "0",
        "LIVE_JOB_LOCK": "0",
        "TWILIO_INBOX_SYNC_ENABLED": "0",
        "TWILIO_TOLLFREE_WATCHDOG_ENABLED": "0",
        "FUNNEL_WATCHDOG": "0",
        "AUTO_WARM_CLOSE_ENABLED": "0",
        "AUTO_INTEREST_NUDGE_ENABLED": "0",
    }

    class _FakeEngine:
        def __init__(self, _cfg) -> None:  # noqa: ANN001
            pass

        def run(self) -> dict[str, int]:
            return {"sent_initial": 0, "sent_followup": 0}

    def _sync_should_not_run(**_kwargs):  # noqa: ANN003
        raise AssertionError("sync_fastmail_inbox should not run when FASTMAIL_INBOX_SYNC_ENABLED=0")

    monkeypatch.setattr("autonomy.tools.live_job.load_dotenv", lambda _path: dict(env))
    monkeypatch.setattr("autonomy.tools.live_job.load_config", lambda _path: cfg)
    monkeypatch.setattr("autonomy.tools.live_job.sync_fastmail_inbox", _sync_should_not_run)
    monkeypatch.setattr("autonomy.tools.live_job.Engine", _FakeEngine)
    monkeypatch.setattr(
        "autonomy.tools.live_job._run_autonomous_lead_hygiene",
        lambda **_kwargs: {"enabled": True, "reason": "ok", "total": 0, "invalid": 0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._deliverability_snapshot",
        lambda *_args, **_kwargs: {"window_days": 7, "emailed": 0, "bounced": 0, "bounce_rate": 0.0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._evaluate_paid_stop_loss",
        lambda **_kwargs: {"blocked": False, "block_reason": "", "zero_revenue_runs": 0, "zero_revenue_days": 0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._collect_sms_channel_state",
        lambda **_kwargs: {
            "daily_sms_cap": 10,
            "daily_sms_interest_reserve": 2,
            "daily_sms_warm_close_reserve": 2,
            "sms_today_all": 0,
            "sms_today": 0,
            "sms_today_followup": 0,
            "sms_today_nudge": 0,
            "sms_today_warm_close": 0,
            "sms_budget_remaining": 10,
            "sms_warm_close_budget_remaining": 0,
            "sms_nudge_budget_remaining": 0,
            "sms_followup_budget_remaining": 0,
        },
    )
    monkeypatch.setattr("autonomy.tools.live_job._maybe_write_call_list", lambda **_kwargs: None)
    monkeypatch.setattr(
        "autonomy.tools.live_job._write_lead_hygiene_daily_report",
        lambda **_kwargs: {"daily_report_path": "", "latest_report_path": ""},
    )
    monkeypatch.setattr("autonomy.tools.live_job.load_scoreboard", lambda *_args, **_kwargs: _zero_board())
    monkeypatch.setattr(
        "autonomy.tools.live_job.build_revenue_lesson",
        lambda **_kwargs: SimpleNamespace(
            bottleneck="none",
            leading_signal="none",
            confidence_pct=100,
            next_actions=["keep running"],
        ),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job.record_revenue_lesson",
        lambda **_kwargs: {"saved": True, "path": "autonomy/state/revenue_learning.jsonl"},
    )
    monkeypatch.setattr("autonomy.tools.live_job._format_report", lambda **_kwargs: "daily report")
    monkeypatch.setattr("autonomy.tools.generate_dashboard.generate", lambda: None)

    monkeypatch.setattr(
        sys,
        "argv",
        ["live_job.py", "--config", "autonomy/state/config.ai-seo.live.json", "--report-path", report_rel],
    )
    live_job_main()
    assert report_path.exists()
    report_path.unlink(missing_ok=True)


def test_live_job_main_email_report_requires_fastmail_creds_even_if_sync_disabled(monkeypatch) -> None:
    env = {
        "REPORT_DELIVERY": "email",
        "FASTMAIL_INBOX_SYNC_ENABLED": "0",
        "LIVE_JOB_LOCK": "0",
    }
    monkeypatch.setattr("autonomy.tools.live_job.load_dotenv", lambda _path: dict(env))
    monkeypatch.setattr(sys, "argv", ["live_job.py", "--config", "autonomy/state/config.ai-seo.live.json"])

    try:
        live_job_main()
        assert False, "expected SystemExit for missing FASTMAIL credentials"
    except SystemExit as exc:
        assert "Missing FASTMAIL_USER in .env" in str(exc)


def test_live_job_main_email_report_requires_smtp_when_fastmail_user_present(monkeypatch) -> None:
    env = {
        "REPORT_DELIVERY": "email",
        "FASTMAIL_INBOX_SYNC_ENABLED": "0",
        "LIVE_JOB_LOCK": "0",
        "FASTMAIL_USER": "agent@example.com",
        "FASTMAIL_FORWARD_TO": "ceo@example.com",
    }
    monkeypatch.setattr("autonomy.tools.live_job.load_dotenv", lambda _path: dict(env))
    monkeypatch.setattr(sys, "argv", ["live_job.py", "--config", "autonomy/state/config.ai-seo.live.json"])

    try:
        live_job_main()
        assert False, "expected SystemExit for missing SMTP password"
    except SystemExit as exc:
        assert "Missing SMTP_PASSWORD in .env" in str(exc)


def test_live_job_main_email_report_requires_recipient(monkeypatch) -> None:
    env = {
        "REPORT_DELIVERY": "email",
        "FASTMAIL_INBOX_SYNC_ENABLED": "0",
        "LIVE_JOB_LOCK": "0",
        "FASTMAIL_USER": "agent@example.com",
        "SMTP_PASSWORD": "pw",
    }
    monkeypatch.setattr("autonomy.tools.live_job.load_dotenv", lambda _path: dict(env))
    monkeypatch.setattr(sys, "argv", ["live_job.py", "--config", "autonomy/state/config.ai-seo.live.json"])

    try:
        live_job_main()
        assert False, "expected SystemExit for missing report recipient"
    except SystemExit as exc:
        assert "Missing FASTMAIL_FORWARD_TO or --report-to" in str(exc)


def test_live_job_main_ntfy_report_requires_topic(monkeypatch) -> None:
    env = {
        "REPORT_DELIVERY": "ntfy",
        "FASTMAIL_INBOX_SYNC_ENABLED": "0",
        "LIVE_JOB_LOCK": "0",
    }
    monkeypatch.setattr("autonomy.tools.live_job.load_dotenv", lambda _path: dict(env))
    monkeypatch.setattr(sys, "argv", ["live_job.py", "--config", "autonomy/state/config.ai-seo.live.json"])

    try:
        live_job_main()
        assert False, "expected SystemExit for missing ntfy topic"
    except SystemExit as exc:
        assert "Missing NTFY_TOPIC" in str(exc)


def test_live_job_main_applies_allow_fastmail_and_approval_defaults(monkeypatch) -> None:
    run_id = uuid.uuid4().hex
    sqlite_path, audit_log = _tmp_state_paths(f"live_job_main_guardrails_{run_id}")
    report_rel = f"autonomy/state/live_job_report_guardrails_{run_id}.txt"
    report_path = Path(report_rel)

    cfg = SimpleNamespace(
        company={
            "name": "AEO Autopilot",
            "booking_url": "https://cal.example.com/audit",
            "kickoff_url": "https://pay.example.com/kickoff",
            "intake_url": "https://example.com/intake",
        },
        compliance={"unsubscribe_url": "https://example.com/unsubscribe?email={{email}}"},
        agents={"outreach": {"daily_send_limit": 1, "followup": {"enabled": True, "daily_send_limit": 1}}},
        lead_sources=[],
        email={"smtp_user": "agent@example.com"},
        storage={"sqlite_path": sqlite_path, "audit_log": audit_log},
    )
    env = {
        "REPORT_DELIVERY": "none",
        "FASTMAIL_INBOX_SYNC_ENABLED": "0",
        "LIVE_JOB_LOCK": "0",
        "ALLOW_FASTMAIL_OUTREACH": "1",
        "APPROVAL_GATE_ENABLED": "1",
        "APPROVAL_REQUIRED_ACTIONS": "",
        "TWILIO_INBOX_SYNC_ENABLED": "0",
        "TWILIO_TOLLFREE_WATCHDOG_ENABLED": "0",
        "FUNNEL_WATCHDOG": "0",
        "AUTO_WARM_CLOSE_ENABLED": "0",
        "AUTO_INTEREST_NUDGE_ENABLED": "0",
    }

    class _FakeEngine:
        def __init__(self, _cfg) -> None:  # noqa: ANN001
            pass

        def run(self) -> dict[str, int]:
            return {"sent_initial": 0, "sent_followup": 0}

    monkeypatch.setattr("autonomy.tools.live_job.load_dotenv", lambda _path: dict(env))
    monkeypatch.setattr("autonomy.tools.live_job.load_config", lambda _path: cfg)
    monkeypatch.setattr("autonomy.tools.live_job.Engine", _FakeEngine)
    monkeypatch.setattr(
        "autonomy.tools.live_job._load_edit_mode_payload",
        lambda **_kwargs: ({}, {"enabled": True, "path": "autonomy/state/edit_mode.overrides.json", "loaded": False, "error": "bad_json"}),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._run_autonomous_lead_hygiene",
        lambda **_kwargs: {"enabled": True, "reason": "ok", "total": 0, "invalid": 0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._deliverability_snapshot",
        lambda *_args, **_kwargs: {"window_days": 7, "emailed": 0, "bounced": 0, "bounce_rate": 0.0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._evaluate_paid_stop_loss",
        lambda **_kwargs: {"blocked": False, "block_reason": "", "zero_revenue_runs": 0, "zero_revenue_days": 0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._collect_sms_channel_state",
        lambda **_kwargs: {
            "daily_sms_cap": 10,
            "daily_sms_interest_reserve": 2,
            "daily_sms_warm_close_reserve": 2,
            "sms_today_all": 0,
            "sms_today": 0,
            "sms_today_followup": 0,
            "sms_today_nudge": 0,
            "sms_today_warm_close": 0,
            "sms_budget_remaining": 10,
            "sms_warm_close_budget_remaining": 0,
            "sms_nudge_budget_remaining": 0,
            "sms_followup_budget_remaining": 0,
        },
    )
    monkeypatch.setattr("autonomy.tools.live_job._maybe_write_call_list", lambda **_kwargs: None)
    monkeypatch.setattr(
        "autonomy.tools.live_job._write_lead_hygiene_daily_report",
        lambda **_kwargs: {"daily_report_path": "", "latest_report_path": ""},
    )
    monkeypatch.setattr("autonomy.tools.live_job.load_scoreboard", lambda *_args, **_kwargs: _zero_board())
    monkeypatch.setattr(
        "autonomy.tools.live_job.build_revenue_lesson",
        lambda **_kwargs: SimpleNamespace(
            bottleneck="none",
            leading_signal="none",
            confidence_pct=100,
            next_actions=["keep running"],
        ),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job.record_revenue_lesson",
        lambda **_kwargs: {"saved": True, "path": "autonomy/state/revenue_learning.jsonl"},
    )
    monkeypatch.setattr("autonomy.tools.live_job._format_report", lambda **_kwargs: "daily report")
    monkeypatch.setattr("autonomy.tools.generate_dashboard.generate", lambda: None)
    monkeypatch.setattr(sys, "argv", ["live_job.py", "--config", "autonomy/state/config.ai-seo.live.json", "--report-path", report_rel])

    live_job_main()
    assert os.environ.get("ALLOW_FASTMAIL_OUTREACH") == "1"
    assert report_path.exists()
    report_path.unlink(missing_ok=True)


def test_live_job_main_non_blocked_deliverability_hits_engine_success_path(monkeypatch) -> None:
    run_id = uuid.uuid4().hex
    sqlite_path, audit_log = _tmp_state_paths(f"live_job_main_ok_{run_id}")
    report_rel = f"autonomy/state/live_job_report_ok_{run_id}.txt"
    report_path = Path(report_rel)

    cfg = SimpleNamespace(
        company={
            "name": "AEO Autopilot",
            "booking_url": "https://cal.example.com/audit",
            "kickoff_url": "https://pay.example.com/kickoff",
            "intake_url": "https://example.com/intake",
        },
        compliance={"unsubscribe_url": "https://example.com/unsubscribe?email={{email}}"},
        agents={"outreach": {"daily_send_limit": 1, "followup": {"enabled": True, "daily_send_limit": 1}}},
        lead_sources=[],
        email={"smtp_user": "agent@example.com"},
        storage={"sqlite_path": sqlite_path, "audit_log": audit_log},
    )
    smtp_secret_key = "SMTP_" + "PASS" + "WORD"
    env = {
        "FASTMAIL_USER": "agent@example.com",
        smtp_secret_key: "pw",
        "REPORT_DELIVERY": "none",
        "LIVE_JOB_LOCK": "0",
        "TWILIO_INBOX_SYNC_ENABLED": "1",
        "TWILIO_TOLLFREE_WATCHDOG_ENABLED": "1",
        "FUNNEL_WATCHDOG": "0",
        "AUTO_WARM_CLOSE_ENABLED": "0",
        "AUTO_INTEREST_NUDGE_ENABLED": "0",
    }

    class _FakeEngine:
        def __init__(self, _cfg) -> None:  # noqa: ANN001
            pass

        def run(self) -> dict[str, int]:
            return {"sent_initial": 1, "sent_followup": 1}

    monkeypatch.setattr("autonomy.tools.live_job.load_dotenv", lambda _path: dict(env))
    monkeypatch.setattr("autonomy.tools.live_job.load_config", lambda _path: cfg)
    monkeypatch.setattr(
        "autonomy.tools.live_job.sync_fastmail_inbox",
        lambda **_kwargs: InboxSyncResult(processed_messages=0, new_bounces=0, new_replies=0, new_opt_outs=0, intake_submissions=0, calendly_bookings=0, stripe_payments=0, last_uid=1),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job.run_twilio_inbox_sync",
        lambda **_kwargs: TwilioInboxResult(reason="ok", interested=0),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job.run_twilio_tollfree_watchdog",
        lambda **_kwargs: TwilioTollfreeWatchdogResult(reason="ok", status="APPROVED", should_alert=False, alert_reason=""),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._run_autonomous_lead_hygiene",
        lambda **_kwargs: {"enabled": True, "reason": "ok", "total": 0, "invalid": 0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._deliverability_snapshot",
        lambda *_args, **_kwargs: {"window_days": 7, "emailed": 0, "bounced": 0, "bounce_rate": 0.0},
    )
    monkeypatch.setattr("autonomy.tools.live_job.Engine", _FakeEngine)
    monkeypatch.setattr(
        "autonomy.tools.live_job._evaluate_paid_stop_loss",
        lambda **_kwargs: {"blocked": False, "block_reason": "", "zero_revenue_runs": 0, "zero_revenue_days": 0},
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job._collect_sms_channel_state",
        lambda **_kwargs: {
            "daily_sms_cap": 10,
            "daily_sms_interest_reserve": 2,
            "daily_sms_warm_close_reserve": 2,
            "sms_today_all": 0,
            "sms_today": 0,
            "sms_today_followup": 0,
            "sms_today_nudge": 0,
            "sms_today_warm_close": 0,
            "sms_budget_remaining": 10,
            "sms_warm_close_budget_remaining": 0,
            "sms_nudge_budget_remaining": 0,
            "sms_followup_budget_remaining": 0,
        },
    )
    monkeypatch.setattr("autonomy.tools.live_job._maybe_write_call_list", lambda **_kwargs: None)
    monkeypatch.setattr(
        "autonomy.tools.live_job._write_lead_hygiene_daily_report",
        lambda **_kwargs: {"daily_report_path": "", "latest_report_path": ""},
    )
    monkeypatch.setattr("autonomy.tools.live_job.load_scoreboard", lambda *_args, **_kwargs: _zero_board())
    monkeypatch.setattr(
        "autonomy.tools.live_job.build_revenue_lesson",
        lambda **_kwargs: SimpleNamespace(
            bottleneck="none",
            leading_signal="none",
            confidence_pct=100,
            next_actions=["keep running"],
        ),
    )
    monkeypatch.setattr(
        "autonomy.tools.live_job.record_revenue_lesson",
        lambda **_kwargs: {"saved": True, "path": "autonomy/state/revenue_learning.jsonl"},
    )
    monkeypatch.setattr("autonomy.tools.live_job._format_report", lambda **_kwargs: "daily report")
    monkeypatch.setattr("autonomy.tools.generate_dashboard.generate", lambda: None)

    monkeypatch.setattr(
        sys,
        "argv",
        ["live_job.py", "--config", "autonomy/state/config.ai-seo.live.json", "--report-path", report_rel],
    )
    live_job_main()
    assert report_path.exists()
    report_path.unlink(missing_ok=True)
