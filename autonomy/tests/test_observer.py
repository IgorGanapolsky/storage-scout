"""Tests for observational memory: Observer, Reflector, and observation-aware AI writer."""
from __future__ import annotations

import atexit
import uuid
from pathlib import Path
from unittest.mock import patch

from autonomy.context_store import ContextStore, Lead
from autonomy.observer import Observer, ObserverConfig, Reflector
from autonomy.ai_writer import AIOutreachWriter

_CLEANUP: list[Path] = []


def _make_store() -> ContextStore:
    """Create a temporary ContextStore that auto-cleans on process exit."""
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path = f"autonomy/state/{tmp}.sqlite3"
    audit_log = f"autonomy/state/{tmp}.jsonl"
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)
    _CLEANUP.extend([store.sqlite_path, store.audit_log])
    return store


@atexit.register
def _cleanup_test_files() -> None:
    for p in _CLEANUP:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def _sample_lead() -> Lead:
    return Lead(
        id="test@example.com",
        name="Jane Doe",
        company="Doe Dental",
        email="test@example.com",
        phone="555-1234",
        service="dental",
        city="Miami",
        state="FL",
        source="manual",
        score=75,
        status="new",
    )


# ── Schema tests ──────────────────────────────────────────────────────


class TestObservationsSchema:
    """Test that the observations table and observed column exist."""

    def test_observations_table_exists(self) -> None:
        store = _make_store()
        cur = store.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='observations'")
        assert cur.fetchone() is not None

    def test_actions_observed_column(self) -> None:
        store = _make_store()
        cur = store.conn.cursor()
        cur.execute("PRAGMA table_info(actions)")
        columns = {row[1] for row in cur.fetchall()}
        assert "observed" in columns


# ── ContextStore observation methods ──────────────────────────────────


class TestContextStoreObservationMethods:
    """Test the observation methods on ContextStore."""

    def test_add_and_get_observation(self) -> None:
        store = _make_store()
        store.add_observation("lead1", "sent initial email, no reply")
        obs = store.get_observations("lead1")
        assert len(obs) == 1
        assert obs[0]["content"] == "sent initial email, no reply"
        assert obs[0]["lead_id"] == "lead1"

    def test_get_observations_empty(self) -> None:
        store = _make_store()
        assert store.get_observations("nonexistent") == []

    def test_replace_observations(self) -> None:
        store = _make_store()
        store.add_observation("lead1", "obs 1")
        store.add_observation("lead1", "obs 2")
        store.add_observation("lead1", "obs 3")
        store.replace_observations("lead1", "condensed: obs 1 + 2 + 3")
        obs = store.get_observations("lead1")
        assert len(obs) == 1
        assert "condensed" in obs[0]["content"]

    def test_get_unobserved_actions(self) -> None:
        store = _make_store()
        store.log_action("agent1", "email.send", "trace1", {"lead_id": "lead1", "status": "sent"})
        store.log_action("agent1", "email.send", "trace2", {"lead_id": "lead1", "status": "sent"})
        actions = store.get_unobserved_actions("lead1")
        assert len(actions) == 2

    def test_mark_actions_observed(self) -> None:
        store = _make_store()
        store.log_action("agent1", "email.send", "trace1", {"lead_id": "lead1", "status": "sent"})
        actions = store.get_unobserved_actions("lead1")
        assert len(actions) == 1
        store.mark_actions_observed([actions[0]["id"]])
        assert store.get_unobserved_actions("lead1") == []

    def test_mark_actions_observed_empty_list(self) -> None:
        store = _make_store()
        store.mark_actions_observed([])  # should not raise

    def test_get_leads_with_unobserved_actions(self) -> None:
        store = _make_store()
        store.log_action("agent1", "email.send", "t1", {"lead_id": "lead1", "status": "sent"})
        store.log_action("agent1", "email.send", "t2", {"lead_id": "lead2", "status": "sent"})
        leads = store.get_leads_with_unobserved_actions()
        assert set(leads) == {"lead1", "lead2"}

    def test_get_message_history(self) -> None:
        store = _make_store()
        store.add_message("lead1", "email", "Subject 1", "Body 1", "sent")
        store.add_message("lead1", "email", "Subject 2", "Body 2", "dry-run")
        history = store.get_message_history("lead1")
        assert len(history) == 2
        assert history[0]["subject"] == "Subject 1"


# ── Observer tests ────────────────────────────────────────────────────


class TestObserver:
    """Test the Observer agent."""

    def test_observe_lead_below_threshold(self) -> None:
        store = _make_store()
        observer = Observer(store, ObserverConfig(observe_threshold=2, reflect_threshold=3))
        store.log_action("agent1", "email.send", "t1", {"lead_id": "lead1", "status": "sent", "kind": "initial"})
        # threshold is 2, only 1 action
        assert observer.observe_lead("lead1") is False

    def test_observe_lead_at_threshold(self) -> None:
        store = _make_store()
        observer = Observer(store, ObserverConfig(observe_threshold=2, reflect_threshold=3))
        store.log_action("agent1", "email.send", "t1", {"lead_id": "lead1", "status": "sent", "kind": "initial", "mode": "live"})
        store.log_action("agent1", "email.send", "t2", {"lead_id": "lead1", "status": "sent", "kind": "followup_2", "mode": "live"})
        assert observer.observe_lead("lead1") is True
        obs = store.get_observations("lead1")
        assert len(obs) == 1
        assert "initial" in obs[0]["content"]
        # Actions should be marked observed
        assert store.get_unobserved_actions("lead1") == []

    def test_observe_all(self) -> None:
        store = _make_store()
        observer = Observer(store, ObserverConfig(observe_threshold=2, reflect_threshold=3))
        for lead_id in ["lead1", "lead2"]:
            store.log_action("a1", "email.send", "t", {"lead_id": lead_id, "status": "sent", "kind": "initial", "mode": "live"})
            store.log_action("a1", "email.send", "t", {"lead_id": lead_id, "status": "sent", "kind": "followup_2", "mode": "live"})
        assert observer.observe_all() == 2

    def test_observe_dry_run_noted(self) -> None:
        store = _make_store()
        observer = Observer(store, ObserverConfig(observe_threshold=2, reflect_threshold=3))
        store.log_action("a1", "email.send", "t", {"lead_id": "lead1", "status": "dry-run", "kind": "initial", "mode": "dry-run"})
        store.log_action("a1", "email.send", "t", {"lead_id": "lead1", "status": "dry-run", "kind": "followup_2", "mode": "dry-run"})
        observer.observe_lead("lead1")
        obs = store.get_observations("lead1")
        assert "dry-run" in obs[0]["content"]


# ── Reflector tests ───────────────────────────────────────────────────


class TestReflector:
    """Test the Reflector agent."""

    def test_reflect_below_threshold(self) -> None:
        store = _make_store()
        reflector = Reflector(store, ObserverConfig(observe_threshold=2, reflect_threshold=3))
        store.add_observation("lead1", "obs 1")
        store.add_observation("lead1", "obs 2")
        assert reflector.reflect_lead("lead1") is False

    def test_reflect_at_threshold(self) -> None:
        store = _make_store()
        reflector = Reflector(store, ObserverConfig(observe_threshold=2, reflect_threshold=3))
        for i in range(4):  # threshold is 3, so 4 triggers reflection
            store.add_observation("lead1", f"[2026-02-{10 + i:02d}] email sent #{i + 1}")
        assert reflector.reflect_lead("lead1") is True
        obs = store.get_observations("lead1")
        assert len(obs) == 1  # condensed to 1

    def test_reflect_preserves_unique_events(self) -> None:
        store = _make_store()
        reflector = Reflector(store, ObserverConfig(observe_threshold=2, reflect_threshold=3))
        store.add_observation("lead1", "event A; event B")
        store.add_observation("lead1", "event B; event C")
        store.add_observation("lead1", "event D")
        store.add_observation("lead1", "event E")
        reflector.reflect_lead("lead1")
        obs = store.get_observations("lead1")
        content = obs[0]["content"]
        assert content.count("event B") == 1  # deduped
        assert "event A" in content
        assert "event C" in content

    def test_reflect_all(self) -> None:
        store = _make_store()
        reflector = Reflector(store, ObserverConfig(observe_threshold=2, reflect_threshold=3))
        for lead_id in ["lead1", "lead2"]:
            for i in range(4):
                store.add_observation(lead_id, f"obs {i}")
        assert reflector.reflect_all() == 2


# ── AIOutreachWriter observation-awareness ────────────────────────────


class TestAIWriterWithObservations:
    """Test that AIOutreachWriter uses observations in prompts."""

    def _make_writer(self, store: ContextStore | None = None) -> AIOutreachWriter:
        return AIOutreachWriter(
            company_name="Test Co",
            intake_url="",
            mailing_address="Addr",
            signature="— Test",
            unsubscribe_url="https://example.com/unsub?email={{email}}",
            store=store,
        )

    def test_observation_context_without_store(self) -> None:
        writer = self._make_writer(store=None)
        assert writer._observation_context(_sample_lead()) == ""

    def test_observation_context_with_store(self) -> None:
        store = _make_store()
        lead = _sample_lead()
        store.add_observation(lead.id, "[2026-02-10] initial email → sent")
        writer = self._make_writer(store=store)
        ctx = writer._observation_context(lead)
        assert "Interaction history:" in ctx
        assert "initial email" in ctx

    def test_system_prompt_includes_observations(self) -> None:
        store = _make_store()
        lead = _sample_lead()
        store.add_observation(lead.id, "[2026-02-10] initial email → sent")
        writer = self._make_writer(store=store)
        obs = writer._observation_context(lead)
        prompt = writer._system_prompt(obs)
        assert "Interaction history:" in prompt
        assert "Test Co" in prompt

    def test_render_falls_back_without_api_key(self) -> None:
        store = _make_store()
        lead = _sample_lead()
        writer = self._make_writer(store=store)
        with patch.dict("os.environ", {}, clear=True):
            result = writer.render(lead)
        assert "subject" in result
        assert "body" in result
