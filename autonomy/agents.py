from dataclasses import dataclass

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
    kickoff_url: str = ""
    booking_url: str = ""
    baseline_example_url: str = ""

    def _render_unsubscribe(self, email: str) -> str:
        return self.unsubscribe_url.replace("{{email}}", email)

    def _proof_line(self) -> str:
        if not self.baseline_example_url:
            return ""
        return f"\nExample baseline (1 page): {self.baseline_example_url}"

    def _booking_line(self) -> str:
        line = "\nReply YES and I'll run the free baseline for you — no call needed."
        if self.kickoff_url:
            line += f"\nOr skip the line and start setup now: {self.kickoff_url} ($249 setup fee)."
        return line

    def _is_med_spa(self, lead: Lead) -> bool:
        return "med spa" in (lead.service or "").lower()

    def _is_dentist(self, lead: Lead) -> bool:
        return "dentist" in (lead.service or "").lower()

    def render(self, lead: Lead) -> dict[str, str]:
        company = lead.company or ("your practice" if self._is_dentist(lead) else "your med spa" if self._is_med_spa(lead) else "your team")
        service = lead.service.lower() if lead.service else "service"
        city = lead.city or "your area"

        if self._is_dentist(lead):
            subject = f"{company} — missed new-patient calls"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"Just tried calling — wanted to ask about missed new-patient calls during lunch or after-hours.\n\n"
                f"We set up missed-call text-back + callback for dental practices. "
                f"Free pilot — you only pay per recovered call ($25/call, no monthly fee).\n\n"
                f"I can run a free 1-page baseline for {company}: estimated missed appointments/week + recovered revenue.\n"
                f"{self._proof_line()}{self._booking_line()}\n\n"
                f"{self.signature}\n"
                f"{self.company_name}\n"
                f"{self.mailing_address}\n\n"
                f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
            )
            return {"subject": subject, "body": body}

        if self._is_med_spa(lead):
            subject = f"{company} — missed calls = empty chairs"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"Quick question: when a new client calls after-hours or during treatments, do you lose the booking?\n\n"
                f"We set up missed-call text-back + booking for med spas. "
                f"Free pilot — you only pay per recovered call ($25/call, no monthly fee).\n\n"
                f"I can run a 1-page baseline for {company}: "
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
            f"Free pilot — you only pay per recovered call ($25/call, no monthly fee).\n\n"
            f"I can run a free baseline that shows exactly how many leads are slipping through.\n"
            f"{self._proof_line()}{self._booking_line()}\n\n"
            f"{self.signature}\n"
            f"{self.company_name}\n"
            f"{self.mailing_address}\n\n"
            f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
        )
        return {"subject": subject, "body": body}

    def render_followup(self, lead: Lead, step: int) -> dict[str, str]:
        step = int(step)
        if step <= 1:
            return self.render(lead)

        company = lead.company or "your team"

        if step == 2:
            if self._is_med_spa(lead):
                subject = f"Re: {company} — baseline numbers?"
                body = (
                    f"Hi {lead.name or 'there'},\n\n"
                    f"If you want the 1-page missed-call baseline, I can run it and send the numbers.\n\n"
                    f"Reply YES and I'll have it in your inbox within 24 hours.\n"
                    f"{self._proof_line()}\n\n"
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
                f"The free baseline shows your actual numbers.\n\n"
                f"Reply YES and I'll run it — takes me 10 minutes, zero effort on your end.\n"
                f"{self._proof_line()}\n\n"
                f"{self.signature}\n"
                f"{self.company_name}\n"
                f"{self.mailing_address}\n\n"
                f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
            )
            return {"subject": subject, "body": body}

        if step == 3:
            subject = f"Re: {company} — closing the loop"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"Not trying to be a pest. If missed calls aren't a priority right now, no worries.\n\n"
                f'Reply YES anytime and I\'ll send the 1-page numbers.\n'
                f"{self._proof_line()}\n\n"
                f"{self.signature}\n"
                f"{self.company_name}\n"
                f"{self.mailing_address}\n\n"
                f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
            )
            return {"subject": subject, "body": body}

        if step == 4:
            service = lead.service.lower() if lead.service else "service"
            subject = f"Re: {company} — quick case study"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"A {service} practice in South Florida was missing 6 calls/day after hours. "
                f"We set up missed-call text-back + auto-callback.\n\n"
                f"Result: 23 recovered appointments in the first month — "
                f"roughly $4,600 in revenue they were leaving on the table.\n\n"
                f"Free pilot, you only pay per recovered call. Reply YES if you want the baseline.\n\n"
                f"{self.signature}\n"
                f"{self.company_name}\n"
                f"{self.mailing_address}\n\n"
                f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
            )
            return {"subject": subject, "body": body}

        # Step 5+: breakup email
        subject = f"Re: {company} — should I close your file?"
        body = (
            f"Hi {lead.name or 'there'},\n\n"
            f"I've reached out a few times about missed-call recovery for {company}. "
            f"I don't want to keep emailing if it's not relevant.\n\n"
            f"If you'd like the free baseline, just reply YES.\n"
            f"Otherwise, no hard feelings — I'll close your file.\n\n"
            f"{self.signature}\n"
            f"{self.company_name}\n"
            f"{self.mailing_address}\n\n"
            f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
        )
        return {"subject": subject, "body": body}
