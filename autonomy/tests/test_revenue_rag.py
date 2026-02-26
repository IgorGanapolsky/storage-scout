from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autonomy.tools.revenue_rag import build_revenue_lesson, record_revenue_lesson


@dataclass
class _Board:
    call_booked_total: int = 0


@dataclass
class _Inbox:
    stripe_payments: int = 0
    calendly_bookings: int = 0


@dataclass
class _TwilioInbox:
    interested: int = 0
    opt_out: int = 0


@dataclass
class _AutoCalls:
    attempted: int = 0
    voicemail: int = 0


@dataclass
class _Sms:
    attempted: int = 0


def test_build_revenue_lesson_detects_interest_conversion_gap() -> None:
    lesson = build_revenue_lesson(
        scoreboard=_Board(call_booked_total=0),
        guardrails={"deliverability_blocked": False, "calls_today": 1, "calls_budget_remaining": 5},
        inbox_result=_Inbox(stripe_payments=0, calendly_bookings=0),
        twilio_inbox_result=_TwilioInbox(interested=2, opt_out=0),
        auto_calls=_AutoCalls(attempted=3, voicemail=1),
        sms_followup=_Sms(attempted=3),
        sources=["https://example.com/source-a"],
    )
    assert lesson.bottleneck == "interest_not_converted_to_booking"
    assert lesson.leading_signal == "interested_reply"
    assert lesson.metrics["interested_signals"] == 2
    assert lesson.confidence_pct >= 80.0


def test_build_revenue_lesson_detects_outreach_paralysis() -> None:
    lesson = build_revenue_lesson(
        scoreboard=_Board(call_booked_total=0),
        guardrails={
            "deliverability_blocked": True,
            "stop_loss_blocked": True,
            "paid_kill_switch": False,
            "calls_today": 0,
            "calls_budget_remaining": 0,
            "sms_today": 0,
            "sms_budget_remaining": 0,
        },
        inbox_result=_Inbox(stripe_payments=0, calendly_bookings=0),
        twilio_inbox_result=_TwilioInbox(interested=0, opt_out=0),
        auto_calls=_AutoCalls(attempted=0, voicemail=0),
        sms_followup=_Sms(attempted=0),
        sources=["https://example.com/source-b"],
    )
    assert lesson.bottleneck == "outreach_paralyzed"
    assert lesson.leading_signal == "none"
    assert "Unblock at least one outbound channel" in lesson.next_actions[0]


def test_build_revenue_lesson_detects_outreach_paralysis_with_paid_kill_switch() -> None:
    lesson = build_revenue_lesson(
        scoreboard=_Board(call_booked_total=0),
        guardrails={
            "deliverability_blocked": True,
            "stop_loss_blocked": False,
            "paid_kill_switch": True,
            "calls_today": 0,
            "calls_budget_remaining": 5,
            "sms_today": 0,
            "sms_budget_remaining": 5,
        },
        inbox_result=_Inbox(stripe_payments=0, calendly_bookings=0),
        twilio_inbox_result=_TwilioInbox(interested=0, opt_out=0),
        auto_calls=_AutoCalls(attempted=1, voicemail=0),
        sms_followup=_Sms(attempted=1),
        sources=["https://example.com/source-c"],
    )
    assert lesson.bottleneck == "outreach_paralyzed"


def test_build_revenue_lesson_does_not_false_positive_paralysis_with_sparse_context() -> None:
    lesson = build_revenue_lesson(
        scoreboard=_Board(call_booked_total=0),
        guardrails={"deliverability_blocked": True},
        inbox_result=_Inbox(stripe_payments=0, calendly_bookings=0),
        twilio_inbox_result=_TwilioInbox(interested=0, opt_out=0),
        auto_calls=None,
        sms_followup=None,
        sources=["https://example.com/source-d"],
    )
    assert lesson.bottleneck == "email_deliverability_blocked"


def test_record_revenue_lesson_dedupes_by_signature(tmp_path: Path) -> None:
    repo_root = tmp_path
    lesson = build_revenue_lesson(
        scoreboard=_Board(call_booked_total=0),
        guardrails={"deliverability_blocked": True, "calls_today": 0, "calls_budget_remaining": 0},
        inbox_result=_Inbox(stripe_payments=0, calendly_bookings=0),
        twilio_inbox_result=_TwilioInbox(interested=0, opt_out=0),
        auto_calls=_AutoCalls(attempted=0, voicemail=0),
        sms_followup=_Sms(attempted=0),
        sources=[],
    )

    first = record_revenue_lesson(repo_root=repo_root, lesson=lesson)
    second = record_revenue_lesson(repo_root=repo_root, lesson=lesson)

    assert first["saved"] is True
    assert second["saved"] is False
    log_path = Path(str(first["path"]))
    lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
