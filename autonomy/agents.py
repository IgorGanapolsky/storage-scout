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
    mailing_address: str
    signature: str
    unsubscribe_url: str

    def render(self, lead: Lead) -> Dict[str, str]:
        subject = f"missed calls = lost jobs for {lead.company or 'your team'}"
        body = (
            f"Hi {lead.name or 'there'},\n\n"
            f"Quick question: are you tracking how many inbound calls go unanswered?\n\n"
            f"We install a 24/7 missed-call recovery + booking system for home service teams. "
            f"I can share a free baseline: missed-call leakage + a recovery estimate. Worth a 15-minute look?\n\n"
            f"{self.signature}\n"
            f"{self.company_name}\n"
            f"{self.mailing_address}\n\n"
            f"Unsubscribe: {self.unsubscribe_url.replace('{{email}}', lead.email)}\n"
        )
        return {"subject": subject, "body": body}
