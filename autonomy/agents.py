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
    booking_url: str = ""
    baseline_example_url: str = ""

    def _render_unsubscribe(self, email: str) -> str:
        return self.unsubscribe_url.replace("{{email}}", email)

    def _render_intake_link(self) -> str:
        if not self.intake_url:
            return ""
        joiner = "&" if "?" in self.intake_url else "?"
        # Do not include PII in query params (e.g., email). Keep UTMs only.
        return f"{self.intake_url}{joiner}utm_source=outreach&utm_medium=email&utm_campaign=baseline"

    def _proof_line(self) -> str:
        if not self.baseline_example_url:
            return ""
        return f"\nExample baseline (1 page): {self.baseline_example_url}"

    def _booking_line(self) -> str:
        if not self.booking_url:
            return ""
        return f"\nBook a free 15-min baseline call: {self.booking_url}"

    def _is_med_spa(self, lead: Lead) -> bool:
        return "med spa" in (lead.service or "").lower()

    def render(self, lead: Lead) -> Dict[str, str]:
        company = lead.company or ("your med spa" if self._is_med_spa(lead) else "your team")
        service = lead.service.lower() if lead.service else "service"
        city = lead.city or "your area"

        if self._is_med_spa(lead):
            subject = f"{company} — missed calls = empty chairs"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"Quick question: when a new client calls after-hours or during treatments, do you lose the booking?\n\n"
                f"We set up missed-call text-back + booking for med spas. I can run a 1-page baseline for {company}: "
                f"estimated missed consults/week + recovered revenue.\n"
                f"{self._proof_line()}{self._booking_line()}\n\n"
                f"{self.signature}\n"
                f"{self.company_name}\n"
                f"{self.mailing_address}\n\n"
                f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
            )
            return {"subject": subject, "body": body}

        subject = f"{company} — after-hours calls"
        body = (
            f"Hi {lead.name or 'there'},\n\n"
            f"Do you know how many calls {company} misses after 5pm or during peak hours?\n\n"
            f"Most {service} businesses in {city} lose 20-35% of inbound calls. "
            f"I run a free 10-min audit that shows exactly how many leads are slipping through.\n"
            f"{self._proof_line()}{self._booking_line()}\n\n"
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

        company = lead.company or "your team"
        
        if step == 2:
            intake_link = self._render_intake_link()
            if self._is_med_spa(lead):
                subject = f"Re: {company} — baseline numbers?"
                body = (
                    f"Hi {lead.name or 'there'},\n\n"
                    f"If you want the 1-page missed-call baseline, I can run it and send the numbers.\n\n"
                    f"2-minute intake:\n{intake_link or self.intake_url}\n"
                    f"{self._proof_line()}{self._booking_line()}\n\n"
                    f"{self.signature}\n"
                    f"{self.company_name}\n"
                    f"{self.mailing_address}\n\n"
                    f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
                )
                return {"subject": subject, "body": body}

            subject = f"Re: {company} — after-hours calls"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"Quick follow-up. One clinic we audited was losing 8 calls/day after hours — "
                f"about $1,600/week in missed bookings.\n\n"
                f"The free audit takes 10 minutes and shows your actual numbers.\n\n"
                f"Want me to run it?\n{intake_link or self.intake_url}\n"
                f"{self._proof_line()}{self._booking_line()}\n\n"
                f"{self.signature}\n"
                f"{self.company_name}\n"
                f"{self.mailing_address}\n\n"
                f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
            )
            return {"subject": subject, "body": body}

        subject = f"Re: {company} — closing the loop"
        body = (
            f"Hi {lead.name or 'there'},\n\n"
            f"Not trying to be a pest. If missed calls aren't a priority right now, no worries.\n\n"
            f'Reply "baseline" anytime and I\'ll send the 1-page numbers.{self._booking_line()}\n'
            f"{self._proof_line()}\n\n"
            f"{self.signature}\n"
            f"{self.company_name}\n"
            f"{self.mailing_address}\n\n"
            f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
        )
        return {"subject": subject, "body": body}
