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
            # Tier 1 Verticals (Highest ROI)
            service_l = lead.service.lower()
            if "dentist" in service_l or "dental" in service_l:
                score += 15
            elif "med spa" in service_l or "aesthetics" in service_l:
                score += 15
            elif "hvac" in service_l or "plumbing" in service_l or "plumber" in service_l:
                score += 10
        if lead.city and lead.state:
            score += 10
            # Regional Priority (South Florida)
            if (lead.state or "").upper() == "FL":
                south_fl_cities = {
                    "miami", "fort lauderdale", "pompano beach", "coral springs",
                    "hollywood", "davie", "plantation", "sunrise", "deerfield beach",
                    "pembroke pines", "miramar", "weston", "tamarac", "margate"
                }
                if (lead.city or "").lower() in south_fl_cities:
                    score += 5
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
            subject = f"{company} — AI visibility gaps"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"Quick note — wanted to ask how easily new patients can discover and book {company} from AI search results.\n\n"
                f"We run done-for-you AI-SEO for dental practices: schema, money-page optimization, and booking-path fixes. "
                f"Pilot starts at $500 with clear before/after reporting.\n\n"
                f"I can run a free 1-page baseline for {company}: AI visibility gaps + revenue-impact opportunities.\n"
                f"{self._proof_line()}{self._booking_line()}\n\n"
                f"{self.signature}\n"
                f"{self.company_name}\n"
                f"{self.mailing_address}\n\n"
                f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
            )
            return {"subject": subject, "body": body}

        if self._is_med_spa(lead):
            subject = f"{company} — AI discovery = filled chairs"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"Quick question: when a new client asks ChatGPT or Google AI for local options, does {company} show up with a clear booking path?\n\n"
                f"We run done-for-you AI-SEO for med spas: schema deployment, offer-page optimization, and conversion-path cleanup. "
                f"Pilot starts at $500 with clear before/after reporting.\n\n"
                f"I can run a 1-page baseline for {company}: "
                f"AI visibility score + revenue-impact opportunities.\n"
                f"{self._proof_line()}{self._booking_line()}\n\n"
                f"{self.signature}\n"
                f"{self.company_name}\n"
                f"{self.mailing_address}\n\n"
                f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
            )
            return {"subject": subject, "body": body}

        subject = f"{company} — local AI visibility"
        body = (
            f"Hi {lead.name or 'there'},\n\n"
            f"Do you know how often {company} appears in AI answers for high-intent {service} searches in {city}?\n\n"
            f"Most {service} businesses in {city} are underrepresented in AI answers and local discovery. "
            f"Pilot starts at $500 one-time with measurable lift targets.\n\n"
            f"I can run a free baseline that shows where revenue is leaking in discovery and booking.\n"
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
                    f"If you want the 1-page AI visibility baseline, I can run it and send the numbers.\n\n"
                    f"Reply YES and I'll have it in your inbox within 24 hours.\n"
                    f"{self._proof_line()}\n\n"
                    f"{self.signature}\n"
                    f"{self.company_name}\n"
                    f"{self.mailing_address}\n\n"
                    f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
                )
                return {"subject": subject, "body": body}

            subject = f"Re: {company} — AI visibility baseline"
            body = (
                f"Hi {lead.name or 'there'},\n\n"
                f"Quick follow-up. One clinic we audited was missing AI answer visibility on core service pages and recovered measurable lead flow in 30 days.\n\n"
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
                f"Not trying to be a pest. If AI-SEO isn't a priority right now, no worries.\n\n"
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
                f"A {service} practice in South Florida was barely appearing in AI answers for high-intent queries. "
                f"We deployed AI-SEO fixes across pages, schema, and booking flow.\n\n"
                f"Result: higher qualified discovery and new booked appointments in the first month.\n\n"
                f"Reply YES if you want the baseline.\n\n"
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
            f"I've reached out a few times about AI-SEO growth for {company}. "
            f"I don't want to keep emailing if it's not relevant.\n\n"
            f"If you'd like the free baseline, just reply YES.\n"
            f"Otherwise, no hard feelings — I'll close your file.\n\n"
            f"{self.signature}\n"
            f"{self.company_name}\n"
            f"{self.mailing_address}\n\n"
            f"Unsubscribe: {self._render_unsubscribe(lead.email)}\n"
        )
        return {"subject": subject, "body": body}
