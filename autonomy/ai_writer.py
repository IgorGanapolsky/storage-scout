import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from .agents import OutreachWriter
from .context_store import ContextStore, Lead

logger = logging.getLogger(__name__)


@dataclass
class AIOutreachWriter:
    company_name: str
    intake_url: str
    mailing_address: str
    signature: str
    unsubscribe_url: str
    booking_url: str = ""
    baseline_example_url: str = ""
    model: str = "gpt-4o"
    store: Optional["ContextStore"] = None

    _fallback: OutreachWriter = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._fallback = OutreachWriter(
            company_name=self.company_name,
            intake_url=self.intake_url,
            mailing_address=self.mailing_address,
            signature=self.signature,
            unsubscribe_url=self.unsubscribe_url,
            booking_url=self.booking_url,
            baseline_example_url=self.baseline_example_url,
        )

    def _get_api_key(self) -> str | None:
        return os.environ.get("OPENAI_API_KEY")

    def _unsubscribe_footer(self, email: str) -> str:
        unsub = self.unsubscribe_url.replace("{{email}}", email)
        return (
            f"\n{self.signature}\n"
            f"{self.company_name}\n"
            f"{self.mailing_address}\n\n"
            f"Unsubscribe: {unsub}\n"
        )

    def _call_openai(self, system: str, user: str) -> str | None:
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("OPENAI_API_KEY not set; falling back to template writer")
            return None
        try:
            import openai

            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.7,
            )
            return response.choices[0].message.content
        except Exception:
            logger.exception("OpenAI API call failed; falling back to template writer")
            return None

    def _system_prompt(self, observations: str = "") -> str:
        base = (
            f"You write short, personalized cold outreach emails for {self.company_name}, "
            f"a missed-call recovery service for local businesses. "
            f"Keep emails under 100 words. Be conversational, not salesy. "
            f"Always include the unsubscribe link."
        )
        if observations:
            base += f"\n\n{observations}"
        return base

    def _lead_context(self, lead: Lead) -> str:
        parts = []
        if lead.name:
            parts.append(f"Contact name: {lead.name}")
        if lead.company:
            parts.append(f"Company: {lead.company}")
        if lead.service:
            parts.append(f"Service type: {lead.service}")
        if lead.city:
            parts.append(f"City: {lead.city}")
        if lead.state:
            parts.append(f"State: {lead.state}")
        return "\n".join(parts)

    def _observation_context(self, lead: Lead) -> str:
        """Build stable observation prefix for prompt caching."""
        if not self.store:
            return ""
        observations = self.store.get_observations(lead.id)
        if not observations:
            return ""
        lines = ["Interaction history:"]
        for obs in observations:
            lines.append(f"- {obs['content']}")
        return "\n".join(lines)

    def _parse_response(self, text: str, lead: Lead) -> dict[str, str]:
        subject = ""
        body = text
        for line in text.splitlines():
            lower = line.lower().strip()
            if lower.startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
                body = text.replace(line, "", 1).strip()
                break
        if not subject:
            subject = f"missed calls = lost jobs for {lead.company or 'your team'}"
        body += self._unsubscribe_footer(lead.email)
        return {"subject": subject, "body": body}

    def render(self, lead: Lead) -> dict[str, str]:
        user_prompt = (
            f"Write an initial cold outreach email.\n\n"
            f"{self._lead_context(lead)}\n\n"
            f"Return the email with the first line as 'Subject: ...' followed by the body."
        )
        obs = self._observation_context(lead)
        result = self._call_openai(self._system_prompt(obs), user_prompt)
        if result is None:
            return self._fallback.render(lead)
        return self._parse_response(result, lead)

    def render_followup(self, lead: Lead, step: int) -> dict[str, str]:
        step = int(step)
        user_prompt = (
            f"Write follow-up email #{step} for a lead who hasn't responded.\n\n"
            f"{self._lead_context(lead)}\n\n"
            f"Return the email with the first line as 'Subject: ...' followed by the body."
        )
        obs = self._observation_context(lead)
        result = self._call_openai(self._system_prompt(obs), user_prompt)
        if result is None:
            return self._fallback.render_followup(lead, step)
        return self._parse_response(result, lead)
