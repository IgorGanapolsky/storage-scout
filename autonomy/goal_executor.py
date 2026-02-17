"""Executes goal-driven tasks using existing autonomy engine components.

Each task_type maps to a concrete executor function that uses
the existing outreach engine, lead generator, and content tools.
"""
import json
import logging
import os
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

from .context_store import ContextStore, now_iso
from .goal_planner import GoalTask, GoalTaskStore

logger = logging.getLogger(__name__)

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ExecutionResult:
    task_id: str
    success: bool
    output: str = ""


class GoalExecutor:
    """Runs planned tasks using existing engine tools."""

    def __init__(self, store: ContextStore) -> None:
        self.store = store
        self.task_store = GoalTaskStore(store)
        self._executors: dict[str, Callable[[GoalTask], ExecutionResult]] = {
            "lead_gen": self._exec_lead_gen,
            "outreach": self._exec_outreach,
            "content": self._exec_content,
            "research": self._exec_research,
            "landing_page": self._exec_landing_page,
            "social": self._exec_social,
            "automation": self._exec_automation,
        }

    def execute_task(self, task: GoalTask) -> ExecutionResult:
        """Execute a single task and update its status."""
        executor = self._executors.get(task.task_type)
        if not executor:
            logger.warning("No executor for task type: %s", task.task_type)
            self.task_store.mark_failed(task.id)
            return ExecutionResult(task_id=task.id, success=False, output=f"Unknown task type: {task.task_type}")

        # Mark as running
        cur = self.store.conn.cursor()
        cur.execute("UPDATE goal_tasks SET status='running' WHERE id=?", (task.id,))
        self.store.conn.commit()

        try:
            result = executor(task)
            if result.success:
                self.task_store.mark_done(task.id)
            else:
                self.task_store.mark_failed(task.id)

            self.store.log_action(
                agent_id="agent.executor.v1",
                action_type=f"task.{task.task_type}",
                trace_id=str(uuid.uuid4()),
                payload={
                    "task_id": task.id,
                    "goal_id": task.goal_id,
                    "description": task.description,
                    "success": result.success,
                    "output": result.output[:500],  # truncate for audit log
                },
            )
            return result
        except Exception as exc:
            logger.exception("Task %s failed: %s", task.id, exc)
            self.task_store.mark_failed(task.id)
            return ExecutionResult(task_id=task.id, success=False, output=str(exc))

    def execute_all_pending(self) -> list[ExecutionResult]:
        """Execute all pending tasks for today. Returns list of results."""
        pending = self.task_store.get_pending_tasks(limit=10)
        results = []
        for task in pending:
            result = self.execute_task(task)
            results.append(result)
            logger.info(
                "Task %s (%s): %s — %s",
                task.id[:8], task.task_type,
                "done" if result.success else "failed",
                result.output[:100],
            )
        return results

    def _exec_lead_gen(self, task: GoalTask) -> ExecutionResult:
        """Generate new leads using the existing lead_gen_broward tool."""
        try:
            script = REPO_ROOT / "autonomy" / "tools" / "lead_gen_broward.py"
            if not script.exists():
                return ExecutionResult(task_id=task.id, success=False, output="lead_gen_broward.py not found")

            api_key = os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_CLOUD_API_KEY") or ""
            if not api_key:
                return ExecutionResult(task_id=task.id, success=False, output="No Google API key in environment")

            categories = (os.environ.get("DAILY_LEADGEN_CATEGORIES") or os.environ.get("LEADGEN_CATEGORIES") or "").strip()
            cmd = ["python3", str(script), "--limit", "10"]
            if categories:
                cmd.extend(["--categories", categories])

            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=120,
                cwd=str(REPO_ROOT),
            )
            output = (result.stdout + result.stderr).strip()
            return ExecutionResult(task_id=task.id, success=result.returncode == 0, output=output[:500])
        except subprocess.TimeoutExpired:
            return ExecutionResult(task_id=task.id, success=False, output="Lead gen timed out after 120s")

    def _exec_outreach(self, task: GoalTask) -> ExecutionResult:
        """Outreach is handled by the main engine.run() — mark as done since engine runs separately."""
        return ExecutionResult(
            task_id=task.id,
            success=True,
            output="Outreach delegated to engine.run() in daily job",
        )

    def _exec_content(self, task: GoalTask) -> ExecutionResult:
        """Log content task for manual execution or future AI generation."""
        content_log = REPO_ROOT / "autonomy" / "state" / "content_queue.jsonl"
        content_log.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": now_iso(),
            "task_id": task.id,
            "goal_id": task.goal_id,
            "description": task.description,
            "status": "queued",
        }
        with content_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return ExecutionResult(
            task_id=task.id,
            success=True,
            output=f"Content task queued: {task.description}",
        )

    def _exec_research(self, task: GoalTask) -> ExecutionResult:
        """Execute research tasks using pipeline data analysis."""
        if "subject lines" in task.description.lower():
            # Analyze outreach performance from DB
            cur = self.store.conn.cursor()
            cur.execute("""
                SELECT subject, status, COUNT(*) as cnt
                FROM messages
                WHERE channel='email'
                GROUP BY subject, status
                ORDER BY cnt DESC
                LIMIT 20
            """)
            rows = cur.fetchall()
            if not rows:
                return ExecutionResult(task_id=task.id, success=True, output="No email data yet for analysis")

            lines = ["Subject Line Performance:"]
            for row in rows:
                lines.append(f"  {row['status']}: {row['subject'][:60]} ({row['cnt']}x)")

            report = "\n".join(lines)
            report_path = REPO_ROOT / "autonomy" / "state" / "research_reports.jsonl"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with report_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": now_iso(), "task_id": task.id, "report": report}) + "\n")
            return ExecutionResult(task_id=task.id, success=True, output=report[:500])

        # Generic research → queue for manual review
        return self._exec_content(task)

    def _exec_landing_page(self, task: GoalTask) -> ExecutionResult:
        """Queue landing page creation task."""
        return self._exec_content(task)

    def _exec_social(self, task: GoalTask) -> ExecutionResult:
        """Queue social engagement task."""
        return self._exec_content(task)

    def _exec_automation(self, task: GoalTask) -> ExecutionResult:
        """Queue automation task."""
        return self._exec_content(task)
