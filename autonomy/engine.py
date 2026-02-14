import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from .agents import LeadScorer, OutreachWriter
from .ai_writer import AIOutreachWriter
from .context_store import ContextStore, Lead
from .observer import Observer, ObserverConfig, Reflector
from .goal_planner import GoalPlanner
from .goal_executor import GoalExecutor
from .providers import EmailConfig, EmailSender, LeadSourceCSV


UTC = timezone.utc
_HEX_LOCAL_RE = re.compile(r"[0-9a-f]{24,}", re.IGNORECASE)


def _email_local_part(email: str) -> str:
    return (email or "").strip().lower().split("@", 1)[0]


def _is_sane_outreach_email(email: str) -> bool:
    """Heuristics to avoid obvious bad scraped addresses (tracking tokens, URL-encoded locals, etc)."""
    local = _email_local_part(email)
    if not local:
        return False
    if "%20" in local or " " in local:
        return False
    if _HEX_LOCAL_RE.fullmatch(local):
        return False
    return True


def _service_matches(lead_service: str, targets: set[str]) -> bool:
    if not targets:
        return True
    raw = (lead_service or "").strip().lower()
    if not raw:
        return False
    return raw in targets


@dataclass
class EngineConfig:
    mode: str
    company: Dict[str, str]
    agents: Dict[str, Dict]
    lead_sources: List[Dict]
    email: Dict[str, str]
    compliance: Dict[str, str]
    storage: Dict[str, str]


class Engine:
    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.store = ContextStore(
            sqlite_path=config.storage["sqlite_path"],
            audit_log=config.storage["audit_log"],
        )
        self.scorer = LeadScorer()
        ai_cfg = config.agents.get("ai_writer", {})
        if ai_cfg.get("enabled"):
            self.writer = AIOutreachWriter(
                company_name=config.company["name"],
                intake_url=config.company.get("intake_url", ""),
                mailing_address=config.company["mailing_address"],
                signature=config.company["signature"],
                unsubscribe_url=config.compliance["unsubscribe_url"],
                booking_url=config.company.get("booking_url", ""),
                model=ai_cfg.get("model", "gpt-4o"),
                store=self.store,
            )
        else:
            self.writer = OutreachWriter(
                company_name=config.company["name"],
                intake_url=config.company.get("intake_url", ""),
                mailing_address=config.company["mailing_address"],
                signature=config.company["signature"],
                unsubscribe_url=config.compliance["unsubscribe_url"],
                booking_url=config.company.get("booking_url", ""),
            )
        email_cfg = EmailConfig(
            provider=config.email["provider"],
            smtp_host=config.email["smtp_host"],
            smtp_port=int(config.email["smtp_port"]),
            smtp_user=config.email["smtp_user"],
            smtp_password_env=config.email["smtp_password_env"],
        )
        self.sender = EmailSender(email_cfg, dry_run=(config.mode == "dry-run"))
        observer_cfg = ObserverConfig(
            observe_threshold=int(config.agents.get("observer", {}).get("observe_threshold", 3)),
            reflect_threshold=int(config.agents.get("observer", {}).get("reflect_threshold", 5)),
        )
        self.observer = Observer(self.store, observer_cfg)
        self.reflector = Reflector(self.store, observer_cfg)

    def ingest_leads(self) -> None:
        for src in self.config.lead_sources:
            if src["type"] == "csv":
                leads = LeadSourceCSV(path=src["path"], source=src["source"]).load()
                for lead in leads:
                    lead.score = self.scorer.score(lead)
                    self.store.upsert_lead(lead)

    def run_initial_outreach(self) -> int:
        outreach_cfg = self.config.agents["outreach"]
        min_score = int(outreach_cfg["min_score"])
        limit = int(outreach_cfg["daily_send_limit"])
        agent_id = outreach_cfg["agent_id"]

        allowed_email_methods = outreach_cfg.get("allowed_email_methods") or []
        if isinstance(allowed_email_methods, str):
            allowed_email_methods = [s.strip() for s in allowed_email_methods.split(",") if s.strip()]
        allowed_email_methods = [str(m).strip().lower() for m in (allowed_email_methods or []) if str(m).strip()]
        email_methods_filter = allowed_email_methods or None

        blocked_local_parts = outreach_cfg.get("blocked_local_parts") or []
        if isinstance(blocked_local_parts, str):
            blocked_local_parts = [s.strip() for s in blocked_local_parts.split(",") if s.strip()]
        blocked_local_parts = {str(v).strip().lower() for v in (blocked_local_parts or []) if str(v).strip()}

        target_services = outreach_cfg.get("target_services") or []
        if isinstance(target_services, str):
            target_services = [s.strip() for s in target_services.split(",") if s.strip()]
        target_services_set = {str(v).strip().lower() for v in (target_services or []) if str(v).strip()}

        bounce_pause = outreach_cfg.get("bounce_pause") or {}
        paused = False
        if bool(bounce_pause.get("enabled", False)):
            window_days = int(bounce_pause.get("window_days", 7) or 7)
            threshold = float(bounce_pause.get("threshold", 0.25) or 0.25)
            min_emailed = int(bounce_pause.get("min_emailed", 20) or 20)
            deliverability = self.store.email_deliverability(days=window_days, email_methods=email_methods_filter)
            if int(deliverability["emailed"] or 0) >= min_emailed and float(deliverability["bounce_rate"] or 0.0) >= threshold:
                paused = True
                self.store.log_action(
                    agent_id=agent_id,
                    action_type="outreach.paused",
                    trace_id=str(uuid.uuid4()),
                    payload={
                        "reason": "bounce_rate_threshold",
                        "threshold": threshold,
                        "min_emailed": min_emailed,
                        "window_days": window_days,
                        "deliverability": deliverability,
                        "email_methods_filter": email_methods_filter,
                    },
                )
        if paused:
            return 0

        sent = 0
        # Fetch extra rows because policy filters can discard many leads (e.g. role inboxes).
        for row in self.store.get_unsent_leads(min_score=min_score, limit=max(limit * 6, 50), email_methods=email_methods_filter):
            lead = Lead(**row)
            if self.store.is_opted_out(lead.email):
                continue
            if not _service_matches(lead.service, target_services_set):
                continue
            if blocked_local_parts and _email_local_part(lead.email) in blocked_local_parts:
                continue
            if not _is_sane_outreach_email(lead.email):
                continue

            trace_id = str(uuid.uuid4())
            msg = self.writer.render(lead)
            status = self.sender.send(
                to_email=lead.email,
                subject=msg["subject"],
                body=msg["body"],
                reply_to=self.config.company["reply_to"],
            )

            self.store.add_message(
                lead_id=lead.id,
                channel="email",
                subject=msg["subject"],
                body=msg["body"],
                status=status,
            )
            if status == "sent":
                self.store.mark_contacted(lead.id)
            self.store.log_action(
                agent_id=agent_id,
                action_type="email.send",
                trace_id=trace_id,
                payload={
                    "kind": "initial",
                    "lead_id": lead.id,
                    "email": lead.email,
                    "status": status,
                    "mode": self.config.mode,
                },
            )
            if status == "sent":
                sent += 1
                if sent >= limit:
                    break
        return sent

    def run_followups(self) -> int:
        outreach_cfg = self.config.agents["outreach"]
        follow_cfg = outreach_cfg.get("followup") or {}
        if not follow_cfg.get("enabled", False):
            return 0

        min_score = int(outreach_cfg["min_score"])
        limit = int(follow_cfg.get("daily_send_limit", 0))
        if limit <= 0:
            return 0

        agent_id = outreach_cfg["agent_id"]
        max_emails = int(follow_cfg.get("max_emails_per_lead", 3))
        min_days = int(follow_cfg.get("min_days_since_last_email", 2))
        cutoff_ts = (datetime.now(UTC) - timedelta(days=min_days)).isoformat()

        allowed_email_methods = outreach_cfg.get("allowed_email_methods") or []
        if isinstance(allowed_email_methods, str):
            allowed_email_methods = [s.strip() for s in allowed_email_methods.split(",") if s.strip()]
        allowed_email_methods = [str(m).strip().lower() for m in (allowed_email_methods or []) if str(m).strip()]
        email_methods_filter = allowed_email_methods or None

        blocked_local_parts = outreach_cfg.get("blocked_local_parts") or []
        if isinstance(blocked_local_parts, str):
            blocked_local_parts = [s.strip() for s in blocked_local_parts.split(",") if s.strip()]
        blocked_local_parts = {str(v).strip().lower() for v in (blocked_local_parts or []) if str(v).strip()}

        target_services = outreach_cfg.get("target_services") or []
        if isinstance(target_services, str):
            target_services = [s.strip() for s in target_services.split(",") if s.strip()]
        target_services_set = {str(v).strip().lower() for v in (target_services or []) if str(v).strip()}

        bounce_pause = outreach_cfg.get("bounce_pause") or {}
        paused = False
        if bool(bounce_pause.get("enabled", False)):
            window_days = int(bounce_pause.get("window_days", 7) or 7)
            threshold = float(bounce_pause.get("threshold", 0.25) or 0.25)
            min_emailed = int(bounce_pause.get("min_emailed", 20) or 20)
            deliverability = self.store.email_deliverability(days=window_days, email_methods=email_methods_filter)
            if int(deliverability["emailed"] or 0) >= min_emailed and float(deliverability["bounce_rate"] or 0.0) >= threshold:
                paused = True
                self.store.log_action(
                    agent_id=agent_id,
                    action_type="outreach.paused",
                    trace_id=str(uuid.uuid4()),
                    payload={
                        "reason": "bounce_rate_threshold",
                        "threshold": threshold,
                        "min_emailed": min_emailed,
                        "window_days": window_days,
                        "deliverability": deliverability,
                        "email_methods_filter": email_methods_filter,
                    },
                )
        if paused:
            return 0

        sent = 0
        for row in self.store.get_followup_leads(
            min_score=min_score,
            limit=max(limit * 6, 50),
            max_emails_per_lead=max_emails,
            cutoff_ts=cutoff_ts,
            email_methods=email_methods_filter,
        ):
            lead = Lead(
                id=row["id"],
                name=row["name"],
                company=row["company"],
                email=row["email"],
                phone=row["phone"],
                service=row["service"],
                city=row["city"],
                state=row["state"],
                source=row["source"],
                score=row["score"],
                status=row["status"],
            )
            if self.store.is_opted_out(lead.email):
                continue
            if not _service_matches(lead.service, target_services_set):
                continue
            if blocked_local_parts and _email_local_part(lead.email) in blocked_local_parts:
                continue
            if not _is_sane_outreach_email(lead.email):
                continue

            sent_count = int(row["email_message_count"] or 0)
            step = sent_count + 1

            trace_id = str(uuid.uuid4())
            msg = self.writer.render_followup(lead, step=step)
            status = self.sender.send(
                to_email=lead.email,
                subject=msg["subject"],
                body=msg["body"],
                reply_to=self.config.company["reply_to"],
            )

            self.store.add_message(
                lead_id=lead.id,
                channel="email",
                subject=msg["subject"],
                body=msg["body"],
                status=status,
            )
            self.store.log_action(
                agent_id=agent_id,
                action_type="email.send",
                trace_id=trace_id,
                payload={
                    "kind": f"followup_{step}",
                    "lead_id": lead.id,
                    "email": lead.email,
                    "status": status,
                    "mode": self.config.mode,
                },
            )
            if status == "sent":
                sent += 1
                if sent >= limit:
                    break
        return sent

    def run(self) -> Dict[str, int]:
        self.ingest_leads()
        observed = self.observer.observe_all()
        reflected = self.reflector.reflect_all()
        sent_initial = self.run_initial_outreach()
        sent_followup = self.run_followups()

        # Goal-driven autonomous tasks
        planner = GoalPlanner(self.store)
        tasks = planner.generate_daily_tasks()
        executor = GoalExecutor(self.store)
        results = executor.execute_all_pending()
        tasks_done = sum(1 for r in results if r.success)
        tasks_failed = sum(1 for r in results if not r.success)

        return {
            "observed": observed,
            "reflected": reflected,
            "sent_initial": sent_initial,
            "sent_followup": sent_followup,
            "goal_tasks_generated": len(tasks),
            "goal_tasks_done": tasks_done,
            "goal_tasks_failed": tasks_failed,
        }


def load_config(path: str) -> EngineConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return EngineConfig(**raw)
