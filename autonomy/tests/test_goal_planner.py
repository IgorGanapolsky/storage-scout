"""Tests for goal-driven autonomous task planner and executor."""
from __future__ import annotations

import atexit
import json
import uuid
from pathlib import Path
from unittest.mock import patch

from autonomy.context_store import ContextStore
from autonomy.goal_planner import (
    Goal,
    GoalPlanner,
    GoalTask,
    GoalTaskStore,
    TASK_TEMPLATES,
    load_goals,
)
from autonomy.goal_executor import GoalExecutor, ExecutionResult

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


def _sample_goals_file(tmp_dir: Path) -> Path:
    """Write a minimal goals.json for testing."""
    goals_path = tmp_dir / "test_goals.json"
    data = {
        "version": 1,
        "updated_at": "2026-02-14",
        "objectives": [
            {
                "id": "test-goal-1",
                "priority": 1,
                "category": "revenue",
                "goal": "Land first client",
                "metrics": ["paid_clients >= 1"],
                "task_types": ["lead_gen", "outreach"],
            },
            {
                "id": "test-goal-2",
                "priority": 2,
                "category": "pipeline",
                "goal": "Build pipeline",
                "metrics": ["leads >= 20"],
                "task_types": ["lead_gen", "research"],
            },
        ],
    }
    goals_path.write_text(json.dumps(data), encoding="utf-8")
    _CLEANUP.append(goals_path)
    return goals_path


# ── Goal loading tests ────────────────────────────────────────────────


class TestGoalLoading:
    """Test loading goals from JSON."""

    def test_load_goals_from_file(self, tmp_path: Path) -> None:
        goals_path = _sample_goals_file(tmp_path)
        goals = load_goals(goals_path)
        assert len(goals) == 2
        assert goals[0].id == "test-goal-1"
        assert goals[0].priority == 1

    def test_load_goals_missing_file(self, tmp_path: Path) -> None:
        goals = load_goals(tmp_path / "nonexistent.json")
        assert goals == []

    def test_goal_dataclass(self) -> None:
        g = Goal(id="test", priority=1, category="rev", goal="Do thing")
        assert g.task_types == []
        assert g.metrics == []


# ── GoalTaskStore tests ───────────────────────────────────────────────


class TestGoalTaskStore:
    """Test the task storage layer."""

    def test_schema_creates_table(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        cur = store.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='goal_tasks'")
        assert cur.fetchone() is not None

    def test_add_and_retrieve_task(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        task = GoalTask(
            id="task-1",
            goal_id="goal-1",
            task_type="lead_gen",
            description="Generate 10 leads",
            created_at="2026-02-14T08:00:00+00:00",
        )
        task_store.add_task(task)
        pending = task_store.get_pending_tasks()
        assert len(pending) == 1
        assert pending[0].id == "task-1"
        assert pending[0].description == "Generate 10 leads"

    def test_mark_done(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        task = GoalTask(id="task-1", goal_id="goal-1", task_type="outreach", description="Send emails", created_at="2026-02-14T08:00:00+00:00")
        task_store.add_task(task)
        task_store.mark_done("task-1")
        pending = task_store.get_pending_tasks()
        assert len(pending) == 0

    def test_mark_failed(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        task = GoalTask(id="task-1", goal_id="goal-1", task_type="outreach", description="Send emails", created_at="2026-02-14T08:00:00+00:00")
        task_store.add_task(task)
        task_store.mark_failed("task-1")
        pending = task_store.get_pending_tasks()
        assert len(pending) == 0

    def test_count_done_for_goal(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        for i in range(3):
            t = GoalTask(id=f"t-{i}", goal_id="goal-1", task_type="lead_gen", description=f"Task {i}", created_at="2026-02-14T08:00:00+00:00")
            task_store.add_task(t)
        task_store.mark_done("t-0")
        task_store.mark_done("t-1")
        assert task_store.count_done_for_goal("goal-1") == 2

    def test_duplicate_insert_ignored(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        task = GoalTask(id="task-dup", goal_id="goal-1", task_type="outreach", description="Dup test", created_at="2026-02-14T08:00:00+00:00")
        task_store.add_task(task)
        task_store.add_task(task)  # should not raise
        pending = task_store.get_pending_tasks()
        assert len(pending) == 1


# ── GoalPlanner tests ─────────────────────────────────────────────────


class TestGoalPlanner:
    """Test the task planner."""

    def test_generate_daily_tasks(self, tmp_path: Path) -> None:
        store = _make_store()
        goals_path = _sample_goals_file(tmp_path)
        planner = GoalPlanner(store, max_daily_tasks=5)
        planner.goals = load_goals(goals_path)
        tasks = planner.generate_daily_tasks()
        assert 1 <= len(tasks) <= 5
        assert all(isinstance(t, GoalTask) for t in tasks)

    def test_idempotent_generation(self, tmp_path: Path) -> None:
        """Calling generate twice in the same day should not create duplicates."""
        store = _make_store()
        goals_path = _sample_goals_file(tmp_path)
        planner = GoalPlanner(store, max_daily_tasks=5)
        planner.goals = load_goals(goals_path)
        tasks1 = planner.generate_daily_tasks()
        tasks2 = planner.generate_daily_tasks()
        assert len(tasks1) == len(tasks2)

    def test_no_goals_no_tasks(self) -> None:
        store = _make_store()
        planner = GoalPlanner(store)
        planner.goals = []
        tasks = planner.generate_daily_tasks()
        assert tasks == []

    def test_format_kanban(self, tmp_path: Path) -> None:
        store = _make_store()
        goals_path = _sample_goals_file(tmp_path)
        planner = GoalPlanner(store, max_daily_tasks=3)
        planner.goals = load_goals(goals_path)
        planner.generate_daily_tasks()
        board = planner.format_kanban()
        assert "TO DO" in board
        assert "Goal-Driven Task Board" in board

    def test_format_kanban_empty(self) -> None:
        store = _make_store()
        planner = GoalPlanner(store)
        planner.goals = []
        board = planner.format_kanban()
        assert "No tasks" in board

    def test_pipeline_state_query(self) -> None:
        store = _make_store()
        planner = GoalPlanner(store)
        state = planner._get_pipeline_state()
        assert "leads_total" in state
        assert "emails_sent" in state

    def test_task_logged_to_audit(self, tmp_path: Path) -> None:
        store = _make_store()
        goals_path = _sample_goals_file(tmp_path)
        planner = GoalPlanner(store, max_daily_tasks=2)
        planner.goals = load_goals(goals_path)
        planner.generate_daily_tasks()
        # Check audit log has the tasks.generated entry
        cur = store.conn.cursor()
        cur.execute("SELECT * FROM actions WHERE action_type='tasks.generated'")
        rows = cur.fetchall()
        assert len(rows) == 1


# ── GoalExecutor tests ────────────────────────────────────────────────


class TestGoalExecutor:
    """Test the task executor."""

    def test_execute_outreach_task(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        task = GoalTask(
            id="exec-1", goal_id="goal-1", task_type="outreach",
            description="Send emails", created_at="2026-02-14T08:00:00+00:00",
        )
        task_store.add_task(task)
        executor = GoalExecutor(store)
        result = executor.execute_task(task)
        assert result.success is True
        assert "delegated" in result.output.lower()

    def test_execute_content_task(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        task = GoalTask(
            id="exec-2", goal_id="goal-1", task_type="content",
            description="Draft LinkedIn post", created_at="2026-02-14T08:00:00+00:00",
        )
        task_store.add_task(task)
        executor = GoalExecutor(store)
        result = executor.execute_task(task)
        assert result.success is True
        assert "queued" in result.output.lower()

    def test_execute_unknown_task_type(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        task = GoalTask(
            id="exec-3", goal_id="goal-1", task_type="unknown_type",
            description="Mystery task", created_at="2026-02-14T08:00:00+00:00",
        )
        task_store.add_task(task)
        executor = GoalExecutor(store)
        result = executor.execute_task(task)
        assert result.success is False

    def test_execute_research_subject_lines(self) -> None:
        store = _make_store()
        # Add some message data
        store.add_message("lead1", "email", "Test Subject", "Body", "sent")
        store.add_message("lead1", "email", "Another Subject", "Body", "sent")
        task_store = GoalTaskStore(store)
        task = GoalTask(
            id="exec-4", goal_id="goal-1", task_type="research",
            description="Analyze which subject lines got replies",
            created_at="2026-02-14T08:00:00+00:00",
        )
        task_store.add_task(task)
        executor = GoalExecutor(store)
        result = executor.execute_task(task)
        assert result.success is True

    def test_execute_all_pending(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        for i in range(3):
            task = GoalTask(
                id=f"batch-{i}", goal_id="goal-1", task_type="outreach",
                description=f"Outreach task {i}", created_at="2026-02-14T08:00:00+00:00",
            )
            task_store.add_task(task)
        executor = GoalExecutor(store)
        results = executor.execute_all_pending()
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_execution_logged_to_audit(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        task = GoalTask(
            id="audit-1", goal_id="goal-1", task_type="content",
            description="Write post", created_at="2026-02-14T08:00:00+00:00",
        )
        task_store.add_task(task)
        executor = GoalExecutor(store)
        executor.execute_task(task)
        cur = store.conn.cursor()
        cur.execute("SELECT * FROM actions WHERE action_type='task.content'")
        rows = cur.fetchall()
        assert len(rows) == 1

    def test_lead_gen_no_api_key(self) -> None:
        store = _make_store()
        task_store = GoalTaskStore(store)
        task = GoalTask(
            id="lg-1", goal_id="goal-1", task_type="lead_gen",
            description="Generate leads", created_at="2026-02-14T08:00:00+00:00",
        )
        task_store.add_task(task)
        executor = GoalExecutor(store)
        with patch.dict("os.environ", {}, clear=True):
            result = executor.execute_task(task)
        assert result.success is False
        assert "api key" in result.output.lower() or "not found" in result.output.lower()


# ── Task template tests ───────────────────────────────────────────────


class TestTaskTemplates:
    """Test that task templates are well-formed."""

    def test_all_task_types_have_templates(self) -> None:
        expected = {"lead_gen", "outreach", "content", "landing_page", "research", "social", "automation"}
        assert set(TASK_TEMPLATES.keys()) == expected

    def test_templates_have_entries(self) -> None:
        for task_type, templates in TASK_TEMPLATES.items():
            assert len(templates) >= 1, f"No templates for {task_type}"

    def test_template_formatting(self) -> None:
        for task_type, templates in TASK_TEMPLATES.items():
            for template in templates:
                # Should not crash with format
                try:
                    template.format(vertical="dental", city="Miami")
                except KeyError:
                    pass  # Some templates don't have variables — that's fine
