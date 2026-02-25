from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any
from dataclasses import dataclass

from autonomy.orchestrator import Node, OrchestrationState
from autonomy.tools.lead_gen_broward import (
    DEFAULT_CATEGORIES,
    build_leads,
    get_api_key,
    load_cities,
    load_existing,
    save_city_index,
    write_leads,
)
from autonomy.tools.lead_hygiene import clean_leads_db
from autonomy.tools.missed_call_audit import run_audit, save_audit
from autonomy.utils import truthy, UTC

log = logging.getLogger(__name__)

@dataclass
class MockInboxResult:
    processed_messages: int = 0
    new_bounces: int = 0
    new_replies: int = 0
    new_opt_outs: int = 0
    intake_submissions: int = 0
    calendly_bookings: int = 0
    stripe_payments: int = 0
    last_uid: int = 0

def _int_env(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip() or default)
    except Exception:
        return int(default)

class IngestionNode(Node):
    """Lead Generation Node: Google Places API."""
    def run(self, state: OrchestrationState) -> OrchestrationState:
        # Determine output CSV from the first configured CSV lead source.
        output_rel = ""
        for src in (getattr(state.config, "lead_sources", []) or []):
            if (src.get("type") or "").lower() == "csv":
                output_rel = str(src.get("path") or "").strip()
                break
        
        if not output_rel:
            state.metadata["ingestion_skipped"] = "no_csv_source"
            return state

        output_path = (state.repo_root / output_rel).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        api_key = get_api_key()
        if not api_key:
            state.metadata["ingestion_skipped"] = "missing_api_key"
            return state

        limit = _int_env(state.env.get("AUTO_LEADGEN_LIMIT"), 0)
        if limit <= 0:
            state.metadata["ingestion_skipped"] = "limit_zero"
            return state

        cities = load_cities(None)
        existing_emails, _, _ = load_existing(output_path)

        # build_leads takes direct params
        new_leads, _ = build_leads(
            api_key=api_key,
            categories=DEFAULT_CATEGORIES,
            cities=cities,
            limit=limit,
            existing_emails=existing_emails,
        )

        if new_leads:
            write_leads(state.sqlite_path, new_leads)
            state.leads_generated = len(new_leads)
            save_city_index(state.repo_root, cities)

        return state

class HygieneNode(Node):
    """Lead Hygiene Node: Email/Phone validation."""
    def run(self, state: OrchestrationState) -> OrchestrationState:
        enabled = truthy(state.env.get("AUTO_LEAD_HYGIENE_ENABLED"), default=True)
        if not enabled:
            state.metadata["hygiene_skipped"] = "disabled"
            return state

        dry_run = truthy(state.env.get("AUTO_LEAD_HYGIENE_DRY_RUN"), default=True) # Default dry-run for safety
        smtp_probe = truthy(state.env.get("AUTO_LEAD_HYGIENE_SMTP_PROBE"), default=False)
        check_mx = truthy(state.env.get("AUTO_LEAD_HYGIENE_MX_CHECK"), default=True)
        sample_limit = max(0, _int_env(state.env.get("AUTO_LEAD_HYGIENE_SAMPLE_LIMIT"), 20))

        try:
            cleaned = clean_leads_db(
                str(state.sqlite_path),
                dry_run=dry_run,
                smtp=smtp_probe,
                check_mx=check_mx,
                sample_limit=sample_limit,
            )
            state.leads_cleaned = cleaned.get("invalid", 0)
            state.metadata["hygiene_report"] = cleaned
        except Exception as e:
            log.warning(f"HygieneNode: {e}")
            # If the database doesn't exist yet, this is expected in first run
            if "no such table" in str(e):
                state.metadata["hygiene_skipped"] = "db_not_initialized"
            else:
                state.errors.append(f"HygieneNode: {e}")

        return state

class AuditNode(Node):
    """Missed Call Audit Node: Probing offices."""
    def run(self, state: OrchestrationState) -> OrchestrationState:
        from autonomy.tools.call_list import generate_call_list

        try:
            call_list = generate_call_list(
                sqlite_path=state.sqlite_path,
                services=DEFAULT_CATEGORIES,
                limit=10,
                min_score=60,
            )
            state.metadata["call_list"] = call_list
        except Exception as e:
            log.warning(f"AuditNode: call list generation failed: {e}")
            return state

        to_audit = [row for row in call_list if getattr(row, "lead_status", None) in {"new", "contacted"}]
        to_audit = to_audit[:3]

        for row in to_audit:
            phone = getattr(row, "phone", None)
            company = getattr(row, "company", None)
            if not phone or not company:
                continue

            try:
                res = run_audit(
                    phone=phone,
                    company=company,
                    service=getattr(row, "service", "dentist"),
                    state=getattr(row, "state", "FL"),
                    num_calls=1,
                    delay_between_secs=0,
                    env=state.env
                )
                save_audit(res)
                state.audits_run.append({"company": company, "miss_rate": res.miss_rate_pct})
            except Exception as e:
                log.error(f"AuditNode: failed for {company}: {e}")

        return state

class OutreachNode(Node):
    """Outreach Node: Twilio Calls, SMS Follow-up, and Interest Nudges."""
    def run(self, state: OrchestrationState) -> OrchestrationState:
        from autonomy.tools.twilio_autocall import run_auto_calls
        from autonomy.tools.twilio_sms import run_sms_followup
        from autonomy.tools.twilio_interest_nudge import run_interest_nudges

        call_rows = state.metadata.get("call_list", [])

        # 1. Run Auto-calls
        call_res = run_auto_calls(
            sqlite_path=state.sqlite_path,
            audit_log=state.audit_log_path,
            env=state.env,
            call_rows=call_rows
        )
        state.calls_attempted = call_res.attempted
        state.metadata["outreach_result"] = call_res

        # 2. Run SMS Follow-ups
        sms_res = run_sms_followup(
            sqlite_path=state.sqlite_path,
            audit_log=state.audit_log_path,
            env=state.env,
        )
        state.sms_sent = sms_res.attempted
        state.metadata["sms_result"] = sms_res

        # 3. Run Interest Nudges
        nudge_res = run_interest_nudges(
            sqlite_path=state.sqlite_path,
            audit_log=state.audit_log_path,
            env=state.env,
        )
        state.nudges_sent = nudge_res.nudged
        state.metadata["interest_nudge_result"] = nudge_res

        return state

class ReportingNode(Node):
    """Reporting Node: Format and deliver the daily summary."""
    def run(self, state: OrchestrationState) -> OrchestrationState:
        from autonomy.tools.scoreboard import load_scoreboard
        from autonomy.tools.live_job import _format_report, _send_email

        # 1. Generate Scoreboard
        scoreboard = load_scoreboard(
            sqlite_path=state.sqlite_path,
            days=30
        )

        # 2. Format Report
        inbox_result = MockInboxResult()
        
        report_txt = _format_report(
            leadgen_new=state.leads_generated,
            lead_hygiene=state.metadata.get("hygiene_report"),
            engine_result={},
            inbox_result=inbox_result,
            scoreboard=scoreboard,
            scoreboard_days=30,
            auto_calls=state.metadata.get("outreach_result"),
            sms_followup=state.metadata.get("sms_result"),
            interest_nudge=state.metadata.get("interest_nudge_result"),
        )

        # 3. Deliver
        smtp_user = state.env.get("SMTP_USER", "hello@callcatcherops.com")
        smtp_password = state.env.get("SMTP_PASSWORD")
        report_to = state.env.get("REPORT_TO_EMAIL")

        if smtp_password and report_to:
            try:
                _send_email(
                    smtp_user=smtp_user,
                    smtp_password=smtp_password,
                    to_email=report_to,
                    subject=f"CallCatcher Ops Report - {datetime.now(UTC).date().isoformat()}",
                    body=report_txt
                )
            except Exception as e:
                log.error(f"ReportingNode: email failed: {e}")

        return state

class ReflectionNode(Node):
    """Reflection Node: Autonomous strategy analysis (Ozkary pattern)."""
    def run(self, state: OrchestrationState) -> OrchestrationState:
        from autonomy.tools.revenue_rag import build_revenue_lesson, record_revenue_lesson
        from autonomy.tools.scoreboard import load_scoreboard

        try:
            # 1. Prepare data objects for reflection
            scoreboard = load_scoreboard(sqlite_path=state.sqlite_path, days=7)
            inbox_result = MockInboxResult()

            # 2. Analyze outcomes
            lesson = build_revenue_lesson(
                scoreboard=scoreboard,
                guardrails={}, # Optional
                inbox_result=inbox_result,
                sources=[str(state.sqlite_path)]
            )

            # 3. Record to RAG
            if lesson:
                record_revenue_lesson(repo_root=state.repo_root, lesson=lesson)
                state.metadata["reflection_bottleneck"] = lesson.bottleneck
                state.metadata["reflection_next_action"] = lesson.next_actions
        except Exception as e:
            log.warning(f"ReflectionNode: {e}")

        return state
