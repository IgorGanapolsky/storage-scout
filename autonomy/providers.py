import csv
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import List

from .context_store import Lead

@dataclass
class LeadSourceCSV:
    path: str
    source: str

    def load(self) -> List[Lead]:
        leads: List[Lead] = []
        path = Path(self.path)
        if not path.exists():
            return leads
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = (row.get("email") or "").strip()
                if not email:
                    continue
                name = (row.get("name") or row.get("contact_name") or "").strip()
                service = (row.get("service") or row.get("category") or "").strip()
                lead_id = f"{email.lower()}"
                leads.append(
                    Lead(
                        id=lead_id,
                        name=name,
                        company=(row.get("company") or "").strip(),
                        email=email,
                        phone=(row.get("phone") or "").strip(),
                        service=service,
                        city=(row.get("city") or "").strip(),
                        state=(row.get("state") or "").strip(),
                        source=self.source,
                    )
                )
        return leads

@dataclass
class EmailConfig:
    provider: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password_env: str

class EmailSender:
    def __init__(self, config: EmailConfig, dry_run: bool) -> None:
        self.config = config
        self.dry_run = dry_run

    def send(self, to_email: str, subject: str, body: str, reply_to: str) -> str:
        if self.dry_run:
            return "dry-run"

        password = os.getenv(self.config.smtp_password_env, "")
        if not password:
            return "missing-smtp-password"

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.config.smtp_user
        msg["To"] = to_email
        msg["Reply-To"] = reply_to
        msg.set_content(body)

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
            server.starttls()
            server.login(self.config.smtp_user, password)
            server.send_message(msg)

        return "sent"
