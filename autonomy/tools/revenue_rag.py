#!/usr/bin/env python3
"""Revenue-learning memory writer for local RAG.

Generates a concise lesson from each live run and stores it under:
`.claude/memory/feedback/revenue-learning-log.jsonl`
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from autonomy.utils import now_utc_iso


@dataclass(frozen=True)
class RevenueLesson:
    as_of_utc: str
    signature: str
    bottleneck: str
    leading_signal: str
    hypothesis: str
    next_actions: list[str]
    confidence_pct: float
    metrics: dict[str, Any]
    sources: list[str]


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _derive_bottleneck(metrics: dict[str, Any]) -> str:
    if _safe_int(metrics.get("stripe_payments")) > 0:
        return "has_revenue"
    if bool(metrics.get("deliverability_blocked")):
        return "email_deliverability_blocked"
    if _safe_int(metrics.get("interested_signals")) > 0 and _safe_int(metrics.get("booked_total")) == 0:
        return "interest_not_converted_to_booking"
    if _safe_int(metrics.get("calls_budget_remaining")) <= 0 and _safe_int(metrics.get("calls_today_billable")) > 0:
        return "call_budget_exhausted"
    if _safe_int(metrics.get("calls_attempted_this_run")) == 0:
        return "no_phone_throughput_this_run"
    if _safe_int(metrics.get("booked_total")) == 0:
        return "zero_bookings"
    return "unclassified"


def _derive_hypothesis_and_actions(bottleneck: str) -> tuple[str, list[str], float]:
    if bottleneck == "has_revenue":
        return (
            "Revenue signal exists; optimization should shift toward repeatable retention and upsell.",
            [
                "Identify which channel produced the payment and increase that channel's daily quota by 10%.",
                "Attach margin tracking to each active account before adding new acquisition spend.",
            ],
            0.85,
        )
    if bottleneck == "email_deliverability_blocked":
        return (
            "Email channel is currently a net-negative; first-dollar path is phone/SMS-led until reputation recovers.",
            [
                "Keep cold email paused while bounce rate stays above configured threshold.",
                "Route daily effort into call + SMS follow-up for qualified local-service leads.",
                "Treat inbound SMS interest as same-day booking opportunities with automated follow-up.",
            ],
            0.92,
        )
    if bottleneck == "interest_not_converted_to_booking":
        return (
            "Prospects show interest but booking conversion friction is blocking first-dollar.",
            [
                "Trigger two automated reminders to interested leads within 24 hours.",
                "Use a single CTA with one link and no extra copy in follow-up replies.",
                "Track interested->booked conversion as the primary KPI for next iterations.",
            ],
            0.88,
        )
    if bottleneck == "call_budget_exhausted":
        return (
            "Throughput cap is limiting same-day opportunities after automation proves stable.",
            [
                "Increase call/SMS daily caps incrementally (10-20%) only while opt-out rate stays acceptable.",
                "Prioritize replied/contacted leads first to maximize conversion per call.",
            ],
            0.78,
        )
    if bottleneck == "no_phone_throughput_this_run":
        return (
            "No phone execution occurred this run, so zero-booking outcome is expected.",
            [
                "Verify paid channel flags and budget caps before each run.",
                "Ensure call list includes high-intent statuses at top of queue.",
            ],
            0.74,
        )
    return (
        "Top-of-funnel and conversion volume are still below threshold for consistent first-dollar probability.",
        [
            "Maintain daily outreach cadence with measurable quotas.",
            "Promote channels that produce positive intent signals and trim low-signal channels.",
        ],
        0.65,
    )


def build_revenue_lesson(
    *,
    scoreboard: Any,
    guardrails: dict[str, Any],
    inbox_result: Any,
    twilio_inbox_result: Any | None = None,
    auto_calls: Any | None = None,
    sms_followup: Any | None = None,
    sources: list[str] | None = None,
) -> RevenueLesson:
    interested_signals = _safe_int(getattr(twilio_inbox_result, "interested", 0))
    booked_total = _safe_int(
        getattr(
            scoreboard,
            "bookings_total",
            getattr(scoreboard, "call_booked_total", 0),
        )
    )
    stripe_payments = _safe_int(
        getattr(
            scoreboard,
            "stripe_payments_total",
            getattr(inbox_result, "stripe_payments", 0),
        )
    )

    metrics: dict[str, Any] = {
        "booked_total": booked_total,
        "stripe_payments": stripe_payments,
        "calendly_bookings": _safe_int(
            getattr(
                scoreboard,
                "calendly_bookings_total",
                getattr(inbox_result, "calendly_bookings", 0),
            )
        ),
        "deliverability_blocked": bool(guardrails.get("deliverability_blocked")),
        "bounce_rate_recent": _safe_float(guardrails.get("deliverability_recent_bounce_rate")),
        "calls_today_billable": _safe_int(guardrails.get("calls_today")),
        "calls_budget_remaining": _safe_int(guardrails.get("calls_budget_remaining")),
        "sms_today_billable": _safe_int(guardrails.get("sms_today")),
        "sms_budget_remaining": _safe_int(guardrails.get("sms_budget_remaining")),
        "calls_attempted_this_run": _safe_int(getattr(auto_calls, "attempted", 0)),
        "sms_attempted_this_run": _safe_int(getattr(sms_followup, "attempted", 0)),
        "interested_signals": interested_signals,
        "opt_out_signals": _safe_int(getattr(twilio_inbox_result, "opt_out", 0)),
    }

    bottleneck = _derive_bottleneck(metrics)
    hypothesis, next_actions, confidence = _derive_hypothesis_and_actions(bottleneck)

    leading_signal = "none"
    if stripe_payments > 0:
        leading_signal = "payment"
    elif _safe_int(metrics["calendly_bookings"]) > 0:
        leading_signal = "booking"
    elif interested_signals > 0:
        leading_signal = "interested_reply"
    elif _safe_int(getattr(auto_calls, "voicemail", 0)) > 0:
        leading_signal = "voicemail_contacts"

    signature_payload = {
        "bottleneck": bottleneck,
        "leading_signal": leading_signal,
        "metrics": metrics,
    }
    signature = str(abs(hash(json.dumps(signature_payload, sort_keys=True))))

    default_sources = [
        "autonomy/state/daily_report_latest.txt",
        "autonomy/state/autonomy_live.sqlite3",
    ]
    merged_sources = [s for s in [*(sources or []), *default_sources] if str(s).strip()]
    dedup_sources = list(dict.fromkeys([str(s).strip() for s in merged_sources]))

    return RevenueLesson(
        as_of_utc=now_utc_iso(),
        signature=signature,
        bottleneck=bottleneck,
        leading_signal=leading_signal,
        hypothesis=hypothesis,
        next_actions=next_actions,
        confidence_pct=round(confidence * 100.0, 1),
        metrics=metrics,
        sources=dedup_sources,
    )


def _read_last_jsonl(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def record_revenue_lesson(*, repo_root: Path, lesson: RevenueLesson) -> dict[str, Any]:
    log_path = (repo_root / ".claude" / "memory" / "feedback" / "revenue-learning-log.jsonl").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    last = _read_last_jsonl(log_path)
    last_signature = str((last or {}).get("signature") or "")
    saved = False

    if lesson.signature != last_signature:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(lesson)) + "\n")
        saved = True

    return {
        "saved": saved,
        "path": str(log_path),
        "entry": asdict(lesson),
    }
