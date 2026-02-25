from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .agents import LeadScorer, OutreachWriter
from .ai_writer import AIOutreachWriter
from .context_store import ContextStore, Lead
from .tracking import tracking_pixel_url, generate_message_id, wrap_html_email
from .goal_executor import GoalExecutor
from .goal_planner import GoalPlanner
from .observer import Observer, ObserverConfig, Reflector
from .outreach_policy import (
    DEFAULT_ALLOWED_EMAIL_METHODS,
    DEFAULT_BLOCKED_LOCAL_PARTS,
    email_local_part,
    is_sane_outreach_email,
    normalize_str_list,
    service_matches,
)
from .providers import EmailConfig, EmailSender, LeadSourceCSV

UTC = timezone.utc


@dataclass(frozen=True)
class OutreachPolicy:
    email_methods_filter: list[str] | None
    blocked_local_parts: set[str]
    target_services: set[str]
    bounce_pause_enabled: bool
    bounce_pause_window_days: int
    bounce_pause_threshold: float
    bounce_pause_min_emailed: int


@dataclass
class EngineConfig:
    mode: str
    company: dict[str, str]
    agents: dict[str, dict]
    lead_sources: list[dict]
    email: dict[str, str]
    compliance: dict[str, str]
    storage: dict[str, str]


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
                kickoff_url=config.company.get("kickoff_url", ""),
                booking_url=config.company.get("booking_url", ""),
                baseline_example_url=config.company.get("baseline_example_url", ""),
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
                kickoff_url=config.company.get("kickoff_url", ""),
                booking_url=config.company.get("booking_url", ""),
                baseline_example_url=config.company.get("baseline_example_url", ""),
            )
        email_cfg = EmailConfig(
            provider=config.email["provider"],
            smtp_host=config.email["smtp_host"],
            smtp_port=int(config.email["smtp_port"]),
            smtp_user=config.email["smtp_user"],
            smtp_password_env=config.email["smtp_password_env"],
        )
        self.sender = EmailSender(email_cfg, dry_run=(config.mode == "dry-run"))

        observer_raw = config.agents.get("observer", {}) or {}
        self.observer_enabled = bool(observer_raw.get("enabled", False))
        self.goals_enabled = bool((config.agents.get("goals", {}) or {}).get("enabled", False))

        observer_cfg = ObserverConfig(
            observe_threshold=int(observer_raw.get("observe_threshold", 3)),
            reflect_threshold=int(observer_raw.get("reflect_threshold", 5)),
        )
        self.observer = Observer(self.store, observer_cfg) if self.observer_enabled else None
        self.reflector = Reflector(self.store, observer_cfg) if self.observer_enabled else None

    def ingest_leads(self) -> None:
        for src in self.config.lead_sources:
            if src["type"] == "csv":
                leads = LeadSourceCSV(path=src["path"], source=src["source"]).load()
                for lead in leads:
                    lead.score = self.scorer.score(lead)
                    self.store.upsert_lead(lead)

    def _build_outreach_policy(self, outreach_cfg: dict) -> OutreachPolicy:
        allowed = normalize_str_list(outreach_cfg.get("allowed_email_methods"))
        if not allowed:
            allowed = DEFAULT_ALLOWED_EMAIL_METHODS[:]
        email_methods_filter = allowed or None

        blocked = set(normalize_str_list(outreach_cfg.get("blocked_local_parts")))
        if not blocked:
            blocked = set(DEFAULT_BLOCKED_LOCAL_PARTS)

        target_services_set = set(normalize_str_list(outreach_cfg.get("target_services")))

        bounce_pause = outreach_cfg.get("bounce_pause") or {}
        enabled = bool(bounce_pause.get("enabled", True))
        window_days = int(bounce_pause.get("window_days", 7) or 7)
        threshold = float(bounce_pause.get("threshold", 0.25) or 0.25)
        min_emailed = int(bounce_pause.get("min_emailed", 20) or 20)

        return OutreachPolicy(
            email_methods_filter=email_methods_filter,
            blocked_local_parts=blocked,
            target_services=target_services_set,
            bounce_pause_enabled=enabled,
            bounce_pause_window_days=window_days,
            bounce_pause_threshold=threshold,
            bounce_pause_min_emailed=min_emailed,
        )

    def _should_pause_outreach(self, *, policy: OutreachPolicy, agent_id: str) -> bool:
        if not policy.bounce_pause_enabled:
            return False

        overall = self.store.email_deliverability(days=policy.bounce_pause_window_days, email_methods=None)
        filtered = self.store.email_deliverability(
            days=policy.bounce_pause_window_days,
            email_methods=policy.email_methods_filter,
        )

        def _over_threshold(d: dict[str, object]) -> bool:
            if int(d.get("emailed") or 0) < policy.bounce_pause_min_emailed:
                return False
            return float(d.get("bounce_rate") or 0.0) >= policy.bounce_pause_threshold

        overall_bad = _over_threshold(overall)
        filtered_bad = _over_threshold(filtered) if policy.email_methods_filter else False

        if not (overall_bad or filtered_bad):
            return False

        self.store.log_action(
            agent_id=agent_id,
            action_type="outreach.paused",
            trace_id=str(uuid.uuid4()),
            payload={
                "reason": "bounce_rate_threshold",
                "trigger": "overall" if overall_bad else "filtered",
                "threshold": policy.bounce_pause_threshold,
                "min_emailed": policy.bounce_pause_min_emailed,
                "window_days": policy.bounce_pause_window_days,
                "deliverability_overall": overall,
                "deliverability_filtered": filtered,
                "email_methods_filter": policy.email_methods_filter,
            },
        )
        return True

    def _lead_passes_outreach_policy(self, lead: Lead, policy: OutreachPolicy) -> bool:
        if not service_matches(lead.service, policy.target_services):
            return False
        local = email_local_part(lead.email)
        if local in policy.blocked_local_parts:
            return False
        return is_sane_outreach_email(lead.email)

    def run_initial_outreach(self) -> int:
        outreach_cfg = self.config.agents["outreach"]
        min_score = int(outreach_cfg["min_score"])
        limit = int(outreach_cfg["daily_send_limit"])
        if limit <= 0:
            return 0
        agent_id = outreach_cfg["agent_id"]

        preflight = self.sender.preflight()
        if not bool(preflight.get("ok", False)):
            self.store.log_action(
                agent_id=agent_id,
                action_type="outreach.blocked",
                trace_id=str(uuid.uuid4()),
                payload={"kind": "initial", **preflight},
            )
            return 0

        policy = self._build_outreach_policy(outreach_cfg)
        if self._should_pause_outreach(policy=policy, agent_id=agent_id):
            return 0

        sent = 0
        # Fetch extra rows because policy filters can discard many leads (e.g. role inboxes).
        for row in self.store.get_unsent_leads(
            min_score=min_score,
            limit=max(limit * 6, 50),
            email_methods=policy.email_methods_filter,
        ):
            lead = Lead(**row)
            if self.store.is_opted_out(lead.email):
                continue
            if not self._lead_passes_outreach_policy(lead, policy):
                continue

            trace_id = str(uuid.uuid4())
            msg = self.writer.render(lead)
            mid = generate_message_id(lead.id, 1)
            pixel_url = tracking_pixel_url(mid)
            html_body = wrap_html_email(msg["body"], pixel_url)
            status = self.sender.send(
                to_email=lead.email,
                subject=msg["subject"],
                body=msg["body"],
                reply_to=self.config.company["reply_to"],
                html_body=html_body,
            )

            self.store.add_message(
                lead_id=lead.id,
                channel="email",
                subject=msg["subject"],
                body=msg["body"],
                status=status,
                step=1,
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
                    "step": 1,
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

        preflight = self.sender.preflight()
        if not bool(preflight.get("ok", False)):
            self.store.log_action(
                agent_id=agent_id,
                action_type="outreach.blocked",
                trace_id=str(uuid.uuid4()),
                payload={"kind": "followup", **preflight},
            )
            return 0

        policy = self._build_outreach_policy(outreach_cfg)
        if self._should_pause_outreach(policy=policy, agent_id=agent_id):
            return 0

        sent = 0
        for row in self.store.get_followup_leads(
            min_score=min_score,
            limit=max(limit * 6, 50),
            max_emails_per_lead=max_emails,
            cutoff_ts=cutoff_ts,
            email_methods=policy.email_methods_filter,
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
                email_method=row["email_method"],
            )
            if self.store.is_opted_out(lead.email):
                continue
            if not self._lead_passes_outreach_policy(lead, policy):
                continue

            sent_count = int(row["email_message_count"] or 0)
            step = sent_count + 1

            trace_id = str(uuid.uuid4())
            msg = self.writer.render_followup(lead, step=step)
            mid = generate_message_id(lead.id, step)
            pixel_url = tracking_pixel_url(mid)
            html_body = wrap_html_email(msg["body"], pixel_url)
            status = self.sender.send(
                to_email=lead.email,
                subject=msg["subject"],
                body=msg["body"],
                reply_to=self.config.company["reply_to"],
                html_body=html_body,
            )

            self.store.add_message(
                lead_id=lead.id,
                channel="email",
                subject=msg["subject"],
                body=msg["body"],
                status=status,
                step=step,
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
                    "step": step,
                    "mode": self.config.mode,
                },
            )
            if status == "sent":
                sent += 1
                if sent >= limit:
                    break
        return sent

    def run(self) -> dict[str, int]:
        self.ingest_leads()
        observed = 0
        reflected = 0
        if self.observer_enabled and self.observer is not None and self.reflector is not None:
            observed = self.observer.observe_all()
            reflected = self.reflector.reflect_all()
        sent_initial = self.run_initial_outreach()
        sent_followup = self.run_followups()

        # Goal-driven autonomous tasks
        tasks = []
        tasks_done = 0
        tasks_failed = 0
        if self.goals_enabled:
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
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return EngineConfig(**raw)
