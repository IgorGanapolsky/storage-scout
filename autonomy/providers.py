import csv
import os
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from .context_store import Lead
from .outreach_policy import infer_email_method
from .utils import truthy


def _is_fastmail_smtp_host(host: str) -> bool:
    host_l = (host or "").strip().lower().rstrip(".")
    # IMPORTANT: Use a dot-boundary check to avoid matching lookalike domains
    # such as "evilfastmail.com".
    return host_l == "fastmail.com" or host_l.endswith(".fastmail.com")


@dataclass
class LeadSourceCSV:
    path: str
    source: str

    @staticmethod
    def _email_method(row: dict, email: str) -> str:
        return infer_email_method(
            email=email,
            raw_method=str(row.get("email_method") or ""),
            notes=str(row.get("notes") or ""),
        )

    def load(self) -> list[Lead]:
        leads: list[Lead] = []
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
                        email_method=self._email_method(row, email),
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

    def preflight(self) -> dict[str, object]:
        """Validate outbound email config before iterating through leads.

        This prevents burning through leads when config is missing (e.g. SMTP password)
        and adds a safety brake for Fastmail programmatic outreach.
        """
        if self.dry_run:
            return {"ok": True, "reason": "dry-run"}

        password_env = self.config.smtp_password_env
        password = os.getenv(password_env, "")
        if not password:
            return {"ok": False, "reason": "missing-smtp-password", "smtp_password_env": password_env}

        host = self.config.smtp_host
        if _is_fastmail_smtp_host(host) and not truthy(os.getenv("ALLOW_FASTMAIL_OUTREACH", "")):
            return {
                "ok": False,
                "reason": "blocked-fastmail-outreach",
                "smtp_host": host,
                "override_env": "ALLOW_FASTMAIL_OUTREACH",
            }

        return {"ok": True, "reason": "ok"}

    _SMTP_RETRIES = 2
    _SMTP_RETRY_DELAY = 3

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

        for attempt in range(self._SMTP_RETRIES):
            try:
                with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as server:
                    server.starttls()
                    server.login(self.config.smtp_user, password)
                    server.send_message(msg)
                return "sent"
            except Exception:
                if attempt < self._SMTP_RETRIES - 1:
                    time.sleep(self._SMTP_RETRY_DELAY)

        return "send-error"
