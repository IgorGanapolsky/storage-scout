import logging
import os
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
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
    kickoff_url: str = ""
    booking_url: str = ""
    baseline_example_url: str = ""
    model: str = "gpt-4o"
    store: Optional["ContextStore"] = None
    prompt_cache_enabled: bool = True
    prompt_cache_ttl_seconds: int = 86400
    prompt_cache_max_entries: int = 5000
    prompt_cache_path: str = ""

    _fallback: OutreachWriter = field(init=False, repr=False)
    _prompt_cache: dict[str, dict[str, object]] = field(init=False, repr=False, default_factory=dict)
    _prompt_cache_abs_path: Path | None = field(init=False, repr=False, default=None)

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
        self.prompt_cache_enabled = bool(self.prompt_cache_enabled)
        self.prompt_cache_ttl_seconds = max(60, int(self.prompt_cache_ttl_seconds or 86400))
        self.prompt_cache_max_entries = max(100, int(self.prompt_cache_max_entries or 5000))
        self._init_prompt_cache()

    def _init_prompt_cache(self) -> None:
        env_enabled = os.environ.get("AI_WRITER_PROMPT_CACHE_ENABLED")
        if env_enabled is not None:
            self.prompt_cache_enabled = str(env_enabled).strip().lower() not in {"0", "false", "no", "off"}
        if not self.prompt_cache_enabled:
            return

        if self.store is not None:
            default_path = self.store.sqlite_path.parent / "ai_writer_prompt_cache.json"
        else:
            default_path = Path("autonomy/state/ai_writer_prompt_cache.json")
        selected = str(os.environ.get("AI_WRITER_PROMPT_CACHE_PATH") or self.prompt_cache_path or "").strip()
        cache_path = Path(selected) if selected else default_path
        self._prompt_cache_abs_path = cache_path.resolve() if cache_path.is_absolute() else (Path.cwd() / cache_path).resolve()
        self._load_prompt_cache()

    def _load_prompt_cache(self) -> None:
        path = self._prompt_cache_abs_path
        if not self.prompt_cache_enabled or path is None or not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        now = time.time()
        entries = raw.get("entries") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "")
            value = str(entry.get("value") or "")
            ts = float(entry.get("ts") or 0.0)
            if not key or not value:
                continue
            if now - ts > float(self.prompt_cache_ttl_seconds):
                continue
            self._prompt_cache[key] = {"value": value, "ts": ts}
        self._prune_prompt_cache()

    def _persist_prompt_cache(self) -> None:
        path = self._prompt_cache_abs_path
        if not self.prompt_cache_enabled or path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "entries": [
                    {"key": key, "value": str(item.get("value") or ""), "ts": float(item.get("ts") or 0.0)}
                    for key, item in self._prompt_cache.items()
                ],
            }
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except Exception:
            logger.exception("Failed to persist AI writer prompt cache")

    def _prune_prompt_cache(self) -> None:
        now = time.time()
        ttl = float(self.prompt_cache_ttl_seconds)
        valid = {
            k: v for k, v in self._prompt_cache.items()
            if now - float(v.get("ts") or 0.0) <= ttl and str(v.get("value") or "")
        }
        if len(valid) > self.prompt_cache_max_entries:
            sorted_items = sorted(
                valid.items(),
                key=lambda kv: float(kv[1].get("ts") or 0.0),
                reverse=True,
            )
            valid = dict(sorted_items[: self.prompt_cache_max_entries])
        self._prompt_cache = valid

    def _prompt_cache_key(self, system: str, user: str) -> str:
        digest = hashlib.sha256()
        digest.update(str(self.model).encode("utf-8"))
        digest.update(b"\n")
        digest.update(str(system).encode("utf-8"))
        digest.update(b"\n")
        digest.update(str(user).encode("utf-8"))
        return digest.hexdigest()

    def _get_cached_prompt_response(self, key: str) -> str | None:
        if not self.prompt_cache_enabled:
            return None
        entry = self._prompt_cache.get(key)
        if not entry:
            return None
        ts = float(entry.get("ts") or 0.0)
        if (time.time() - ts) > float(self.prompt_cache_ttl_seconds):
            return None
        value = str(entry.get("value") or "")
        return value if value else None

    def _put_cached_prompt_response(self, key: str, value: str) -> None:
        if not self.prompt_cache_enabled or not key or not value:
            return
        self._prompt_cache[key] = {"value": str(value), "ts": float(time.time())}
        self._prune_prompt_cache()
        self._persist_prompt_cache()

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
        cache_key = self._prompt_cache_key(system, user)
        cached = self._get_cached_prompt_response(cache_key)
        if cached is not None:
            return cached

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
            content = str(response.choices[0].message.content or "")
            if content:
                self._put_cached_prompt_response(cache_key, content)
            return content or None
        except Exception:
            logger.exception("OpenAI API call failed; falling back to template writer")
            return None

    def _system_prompt(self, observations: str = "") -> str:
        base = (
            f"You write short, personalized cold outreach emails for {self.company_name}, "
            f"an autonomous AI-SEO service for local businesses. "
            f"Keep emails under 100 words. Be conversational, not salesy. "
            f"CTA can be 'Reply YES' or a direct link to the setup page if the business has verified pain. "
            f"Setup link: {self.kickoff_url}. "
            f"Frame as: done-for-you AI-SEO sprint with baseline + implementation plan. "
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
            subject = f"AEO execution plan for {lead.company or 'your team'}"
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
