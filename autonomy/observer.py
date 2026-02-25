from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from .context_store import ContextStore

logger = logging.getLogger(__name__)


@dataclass
class ObserverConfig:
    observe_threshold: int = 3  # min unobserved actions before observing
    reflect_threshold: int = 5  # max observations before reflecting


class Observer:
    """Compresses raw audit actions into per-lead observation notes.

    Inspired by Mastra's observational memory: instead of RAG retrieval,
    we maintain a compressed, append-only log of what happened with each
    lead. This gives the AI writer stable context for personalization.
    """

    def __init__(self, store: ContextStore, config: ObserverConfig | None = None) -> None:
        self.store = store
        self.config = config or ObserverConfig()

    def _compress_actions(self, lead_id: str, actions: list) -> str:
        """Compress raw actions into a dated observation note."""
        lines = []
        for action in actions:
            ts = action["ts"]
            action_type = action["action_type"]
            payload = json.loads(action["payload_json"])
            kind = payload.get("kind", "")
            status = payload.get("status", "")
            mode = payload.get("mode", "")

            date_str = ts[:10] if ts else "unknown"

            if action_type == "email.send":
                mode_note = f" [{mode}]" if mode == "dry-run" else ""
                lines.append(f"[{date_str}] {kind} email → {status}{mode_note}")
            else:
                lines.append(f"[{date_str}] {action_type}: {status}")

        # Add message context
        messages = self.store.get_message_history(lead_id)
        if messages:
            sent_count = sum(1 for m in messages if m["status"] == "sent")
            channels = set(m["channel"] for m in messages)
            lines.append(f"Total: {sent_count} sent via {', '.join(channels)}")

        return "; ".join(lines)

    def observe_lead(self, lead_id: str) -> bool:
        """Compress unobserved actions for a single lead. Returns True if observation was created."""
        actions = self.store.get_unobserved_actions(lead_id)
        if len(actions) < self.config.observe_threshold:
            return False

        content = self._compress_actions(lead_id, actions)
        self.store.add_observation(lead_id, content)
        self.store.mark_actions_observed([action["id"] for action in actions])
        logger.info("Observed %d actions for lead %s", len(actions), lead_id)
        return True

    def observe_all(self) -> int:
        """Run observation pass on all leads with unobserved actions. Returns count of leads observed."""
        lead_ids = self.store.get_leads_with_unobserved_actions()
        observed = 0
        for lead_id in lead_ids:
            if self.observe_lead(lead_id):
                observed += 1
        return observed


class Reflector:
    """Condenses accumulated observations when they exceed a threshold.

    Unlike compaction (which produces lossy summaries), reflection
    reorganizes and merges observations while preserving the event-based
    decision log structure.
    """

    def __init__(self, store: ContextStore, config: ObserverConfig | None = None) -> None:
        self.store = store
        self.config = config or ObserverConfig()

    def _condense_observations(self, observations: list) -> str:
        """Merge multiple observations into a condensed log, dropping redundant info."""
        all_entries = []
        for obs in observations:
            all_entries.append(obs["content"])

        # Deduplicate while preserving chronological order
        seen = set()
        unique = []
        for entry in all_entries:
            for part in entry.split("; "):
                part = part.strip()
                if part and part not in seen:
                    seen.add(part)
                    unique.append(part)

        return "; ".join(unique)

    def reflect_lead(self, lead_id: str) -> bool:
        """Condense observations for a lead if they exceed threshold. Returns True if reflected."""
        observations = self.store.get_observations(lead_id)
        if len(observations) <= self.config.reflect_threshold:
            return False

        condensed = self._condense_observations(observations)
        self.store.replace_observations(lead_id, condensed)
        logger.info("Reflected %d observations for lead %s into 1", len(observations), lead_id)
        return True

    def reflect_all(self) -> int:
        """Run reflection on all leads. Returns count of leads reflected."""
        cur = self.store.conn.cursor()
        cur.execute(
            "SELECT lead_id, COUNT(*) as cnt FROM observations GROUP BY lead_id HAVING cnt > ?",
            (self.config.reflect_threshold,),
        )
        reflected = 0
        for row in cur.fetchall():
            if self.reflect_lead(row["lead_id"]):
                reflected += 1
        return reflected
