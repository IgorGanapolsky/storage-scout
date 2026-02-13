import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from .agents import LeadScorer, OutreachWriter
from .context_store import ContextStore, Lead
from .providers import EmailConfig, EmailSender, LeadSourceCSV


UTC = timezone.utc


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
        self.writer = OutreachWriter(
            company_name=config.company["name"],
            intake_url=config.company.get("intake_url", ""),
            mailing_address=config.company["mailing_address"],
            signature=config.company["signature"],
            unsubscribe_url=config.compliance["unsubscribe_url"],
        )
        email_cfg = EmailConfig(
            provider=config.email["provider"],
            smtp_host=config.email["smtp_host"],
            smtp_port=int(config.email["smtp_port"]),
            smtp_user=config.email["smtp_user"],
            smtp_password_env=config.email["smtp_password_env"],
        )
        self.sender = EmailSender(email_cfg, dry_run=(config.mode == "dry-run"))

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

        sent = 0
        for row in self.store.get_unsent_leads(min_score=min_score, limit=limit):
            lead = Lead(**row)
            if self.store.is_opted_out(lead.email):
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

        sent = 0
        for row in self.store.get_followup_leads(
            min_score=min_score,
            limit=limit,
            max_emails_per_lead=max_emails,
            cutoff_ts=cutoff_ts,
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
        return sent

    def run(self) -> Dict[str, int]:
        self.ingest_leads()
        sent_initial = self.run_initial_outreach()
        sent_followup = self.run_followups()
        return {"sent_initial": sent_initial, "sent_followup": sent_followup}


def load_config(path: str) -> EngineConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return EngineConfig(**raw)
