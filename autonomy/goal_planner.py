"""Goal-driven autonomous task planner for CallCatcher Ops.

Loads business goals, evaluates current state, generates and tracks
daily tasks that advance the highest-priority unmet objectives.
"""

import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .context_store import ContextStore, now_iso

logger = logging.getLogger(__name__)

UTC = timezone.utc
GOALS_PATH = Path(__file__).resolve().parent / "goals.json"


@dataclass
class Goal:
    id: str
    priority: int
    category: str
    goal: str
    metrics: List[str] = field(default_factory=list)
    task_types: List[str] = field(default_factory=list)


@dataclass
class GoalTask:
    id: str
    goal_id: str
    task_type: str
    description: str
    status: str = "pending"  # pending | running | done | failed
    created_at: str = ""
    completed_at: str = ""


# Map task_types to concrete executable descriptions.
# The planner picks from these based on which goal needs work.
TASK_TEMPLATES: Dict[str, List[str]] = {
    "phone_outreach": [
        "Call 10 dentist leads from the call list CSV and log outcomes",
        "Call non-bounced contacted leads to follow up on baseline offer",
        "Call new dentist leads with phone numbers and ask for the owner/office manager",
        "Leave voicemails for unreachable leads and send post-voicemail follow-up email",
    ],
    "lead_gen": [
        "Scrape 10 new {vertical} businesses in Broward County via Google Places and add to outreach DB",
        "Research top 5 {vertical} businesses in {city} with public phone numbers and direct emails",
        "Find 10 new leads from Yelp/Google Maps for {vertical} in South Florida with direct email addresses",
    ],
    "outreach": [
        "Send post-call follow-up emails to leads who said 'email me' (direct emails only)",
        "Send follow-up emails to leads contacted 3+ days ago with no reply (direct emails only)",
        "Draft personalized cold email for leads in the {vertical} vertical (direct email only)",
    ],
    "content": [
        "Draft LinkedIn post about missed-call revenue leak for {vertical} businesses",
        "Write a short case-study-style post with industry miss-rate benchmarks",
        "Draft a LinkedIn poll asking local business owners about their call handling",
    ],
    "landing_page": [
        "Build a vertical-specific landing page for {vertical} at docs/callcatcherops/{vertical}.html",
        "Add testimonial/social-proof section to the {vertical} landing page",
    ],
    "research": [
        "Analyze which outreach subject lines got replies vs bounces in the last 7 days",
        "Research competitor missed-call services and document pricing/features",
        "Identify top 3 Facebook groups where {vertical} owners discuss operations",
    ],
    "social": [
        "Engage with 5 LinkedIn posts from local {vertical} business owners",
        "Connect with 10 {vertical} business owners on LinkedIn with personalized notes",
    ],
    "automation": [
        "Implement automatic lead scoring for new intake form submissions",
        "Add webhook handler to score and route new leads from intake form",
    ],
}

VERTICALS = ["med spa", "dental", "HVAC", "plumbing", "home services"]
CITIES = ["Fort Lauderdale", "Coral Springs", "Boca Raton", "Pompano Beach", "Plantation"]


class GoalTaskStore:
    """Manages the goal_tasks table in the existing autonomy SQLite DB."""

    def __init__(self, store: ContextStore) -> None:
        self.conn = store.conn
        self.store = store
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS goal_tasks (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        self.conn.commit()

    def add_task(self, task: GoalTask) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO goal_tasks (id, goal_id, task_type, description, status, created_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task.id, task.goal_id, task.task_type, task.description, task.status, task.created_at, task.completed_at),
        )
        self.conn.commit()

    def mark_done(self, task_id: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE goal_tasks SET status='done', completed_at=? WHERE id=?",
            (now_iso(), task_id),
        )
        self.conn.commit()

    def mark_failed(self, task_id: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE goal_tasks SET status='failed', completed_at=? WHERE id=?",
            (now_iso(), task_id),
        )
        self.conn.commit()

    def get_pending_tasks(self, limit: int = 10) -> List[GoalTask]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, goal_id, task_type, description, status, created_at, completed_at FROM goal_tasks WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
        return [GoalTask(**dict(row)) for row in cur.fetchall()]

    def get_tasks_today(self) -> List[GoalTask]:
        today = datetime.now(UTC).date().isoformat()
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, goal_id, task_type, description, status, created_at, completed_at FROM goal_tasks WHERE created_at >= ? ORDER BY created_at ASC",
            (today,),
        )
        return [GoalTask(**dict(row)) for row in cur.fetchall()]

    def count_done_for_goal(self, goal_id: str) -> int:
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT COUNT(*) FROM goal_tasks WHERE goal_id=? AND status='done'",
            (goal_id,),
        ).fetchone()
        return int(row[0]) if row else 0


def load_goals(path: Path | None = None) -> List[Goal]:
    """Load goals from the goals.json brain dump."""
    p = path or GOALS_PATH
    if not p.exists():
        logger.warning("Goals file not found: %s", p)
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [Goal(**obj) for obj in raw.get("objectives", [])]


class GoalPlanner:
    """Generates daily tasks from business goals and current system state."""

    def __init__(self, store: ContextStore, max_daily_tasks: int = 5) -> None:
        self.store = store
        self.task_store = GoalTaskStore(store)
        self.max_daily_tasks = max_daily_tasks
        self.goals = load_goals()

    def _get_pipeline_state(self) -> Dict[str, int]:
        """Query current pipeline counts from the DB."""
        cur = self.store.conn.cursor()
        counts: Dict[str, int] = {}

        for status in ("new", "contacted", "replied", "bounced"):
            row = cur.execute("SELECT COUNT(*) FROM leads WHERE status=?", (status,)).fetchone()
            counts[f"leads_{status}"] = int(row[0]) if row else 0

        row = cur.execute("SELECT COUNT(*) FROM messages WHERE status='sent'").fetchone()
        counts["emails_sent"] = int(row[0]) if row else 0

        row = cur.execute("SELECT COUNT(*) FROM leads").fetchone()
        counts["leads_total"] = int(row[0]) if row else 0

        return counts

    def _pick_template(self, task_type: str) -> str:
        """Pick a random template for a task type with variable substitution."""
        templates = TASK_TEMPLATES.get(task_type, [])
        if not templates:
            return f"Execute {task_type} task for CallCatcher Ops"
        template = random.choice(templates)
        vertical = random.choice(VERTICALS)
        city = random.choice(CITIES)
        return template.format(vertical=vertical, city=city)

    def _should_generate_tasks(self) -> bool:
        """Only generate tasks if we haven't already generated today's batch."""
        today_tasks = self.task_store.get_tasks_today()
        return len(today_tasks) < self.max_daily_tasks

    def generate_daily_tasks(self) -> List[GoalTask]:
        """Generate today's autonomous task list based on goal priorities."""
        if not self._should_generate_tasks():
            logger.info("Daily tasks already generated; skipping")
            return self.task_store.get_tasks_today()

        if not self.goals:
            logger.warning("No goals loaded; cannot generate tasks")
            return []

        pipeline = self._get_pipeline_state()
        tasks: List[GoalTask] = []

        # Sort goals by priority (1 = highest)
        sorted_goals = sorted(self.goals, key=lambda g: g.priority)

        # Distribute tasks across top goals, weighted by priority
        slots_remaining = self.max_daily_tasks
        for goal in sorted_goals:
            if slots_remaining <= 0:
                break

            # Higher priority goals get more task slots
            slots_for_goal = max(1, slots_remaining // max(1, len(sorted_goals) - len(tasks)))
            if goal.priority <= 2:
                slots_for_goal = min(slots_remaining, 2)  # top 2 priorities get up to 2 tasks each

            for _ in range(min(slots_for_goal, slots_remaining)):
                if not goal.task_types:
                    continue
                task_type = random.choice(goal.task_types)
                description = self._pick_template(task_type)

                task = GoalTask(
                    id=str(uuid.uuid4()),
                    goal_id=goal.id,
                    task_type=task_type,
                    description=description,
                    status="pending",
                    created_at=now_iso(),
                )
                self.task_store.add_task(task)
                tasks.append(task)
                slots_remaining -= 1

            if slots_remaining <= 0:
                break

        # Log task generation to audit trail
        self.store.log_action(
            agent_id="agent.planner.v1",
            action_type="tasks.generated",
            trace_id=str(uuid.uuid4()),
            payload={
                "date": datetime.now(UTC).date().isoformat(),
                "task_count": len(tasks),
                "pipeline_state": pipeline,
                "tasks": [{"id": t.id, "goal_id": t.goal_id, "type": t.task_type, "desc": t.description} for t in tasks],
            },
        )

        logger.info("Generated %d daily tasks across %d goals", len(tasks), len(set(t.goal_id for t in tasks)))
        return tasks

    def format_kanban(self) -> str:
        """Format today's tasks as a text-based Kanban board."""
        today_tasks = self.task_store.get_tasks_today()
        if not today_tasks:
            return "No tasks generated today."

        pending = [t for t in today_tasks if t.status == "pending"]
        running = [t for t in today_tasks if t.status == "running"]
        done = [t for t in today_tasks if t.status == "done"]
        failed = [t for t in today_tasks if t.status == "failed"]

        lines = ["Goal-Driven Task Board", "=" * 40, ""]

        if pending:
            lines.append("📋 TO DO")
            for t in pending:
                lines.append(f"  • [{t.goal_id}] {t.description}")
            lines.append("")

        if running:
            lines.append("🔄 IN PROGRESS")
            for t in running:
                lines.append(f"  • [{t.goal_id}] {t.description}")
            lines.append("")

        if done:
            lines.append("✅ DONE")
            for t in done:
                lines.append(f"  • [{t.goal_id}] {t.description}")
            lines.append("")

        if failed:
            lines.append("❌ FAILED")
            for t in failed:
                lines.append(f"  • [{t.goal_id}] {t.description}")
            lines.append("")

        return "\n".join(lines)
