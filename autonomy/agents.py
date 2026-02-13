from dataclasses import dataclass
from typing import Dict

from .context_store import Lead

@dataclass
class LeadScorer:
    def score(self, lead: Lead) -> int:
        score = 0
        if lead.company:
            score += 20
        if lead.phone:
            score += 15
        if lead.service:
            score += 10
        if lead.city and lead.state:
            score += 10
        if lead.email:
            score += 20
        return min(score, 100)

@dataclass
class OutreachWriter:
    company_name: str
    intake_url: str
    mailing_address: str
    signature: str
    unsubscribe_url: str

    def _render_unsubscribe(self, email: str) -> str:
        return self.unsubscribe_url.replace("{{email}}", email)

    def _render_intake_link(self) -> str:
        if not self.intake_url:
            return ""
        joiner = "&" if "?" in self.intake_url else "?"
        # Do not include PII in query params (e.g., email). Keep UTMs only.
        return f"{self.intake_url}{joiner}utm_source=outreach&utm_medium=email&utm_campaign=baseline"

    def render(self, lead: Lead) -> Dict[str, str]:
        subject = f"missed calls = lost jobs for {lead.company or 'your team'}"
        body = (
            f"Hi {lead.name or 'there'},\n\n"
            f"Quick question: are you tracking how many inbound calls go unanswered?\n\n"
            f"We install missed-call recovery + booking automation for local service businesses. "
            f"I can share a free baseline: missed-call leakage + a recovery estimate. Worth a 15-minute look?\n\n"
            f"{self.signature}\n"
            f"{self.company_name}\n"
            f"{self.mailing_address}\n\n"
            f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
        )
        return {"subject": subject, "body": body}

    def render_followup(self, lead: Lead, step: int) -> Dict[str, str]:
        step = int(step)
        if step <= 1:
            return self.render(lead)

        intake_link = self._render_intake_link()

        if step == 2:
            subject = f"baseline recovery numbers for {lead.company or 'your team'}"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"Quick follow-up. If you want the free missed-call baseline, I can run it and send the results.\n\n"
                f"If you prefer, you can share details via this 2-minute intake:\n"
                f"{intake_link or self.intake_url}\n\n"
                f"{self.signature}\n"
                f"{self.company_name}\n"
                f"{self.mailing_address}\n\n"
                f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
            )
            return {"subject": subject, "body": body}

        subject = "close the loop?"
        body = (
            f"Hi {lead.name or 'there'},\n\n"
            f"If missed calls are not a priority right now, no worries.\n"
            f'If you want the baseline later, reply "baseline" and I will send it over.\n\n'
            f"{self.signature}\n"
            f"{self.company_name}\n"
            f"{self.mailing_address}\n\n"
            f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
        )
        return {"subject": subject, "body": body}
