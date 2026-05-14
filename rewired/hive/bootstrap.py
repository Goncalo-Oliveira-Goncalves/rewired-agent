from __future__ import annotations
from pathlib import Path
from typing import Optional

from .loader import load_hive
from .schema import HiveTree, AgentNode
from .task_manager import HiveTaskManager, TaskRecord


_DEFAULT_QUEEN_PROMPT_SUFFIX = """
You are operating inside re:wired, a hierarchical AI swarm built on Hermes Agent.

## Your Role
You are the queen bee — the single agent that speaks directly with the user. Your job is to:
1. Understand the user's request deeply before acting
2. Decompose the request into delegatable sub-tasks
3. Assign sub-tasks to generals (or handle them yourself if alone)
4. Synthesize all results into a clean, concise report for the user
5. Provide an estimated completion time at the start of each task

## Hive Hierarchy
{hive_tree}

## Active Task
- Task ID: {task_id}
- Task Name: {task_name}
- Started: {started_at}

## Your Responsibilities
- Name tasks in kebab-case (e.g., "build-the-website")
- Estimate completion time honestly — account for sub-task complexity
- Write a REPORT.md at the end: concise, action-oriented, ≤ 300 words
- Only escalate to the user when truly blocked or when a decision is needed
- Track all work via the kanban tool

## When Working Alone (No Generals)
If no generals exist yet, you may create them by writing AGENT.md files in agents/queen-bee/general-name/. You can then act as general yourself for the current task.
"""


class HiveBootstrap:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.agents_dir = self.base_dir / "agents"
        self.tasks_dir = self.base_dir / "tasks"
        self._hive: Optional[HiveTree] = None
        self._task_manager = HiveTaskManager(self.tasks_dir)

    def _get_hive(self) -> HiveTree:
        if self._hive is None:
            self._hive = load_hive(self.agents_dir)
        return self._hive

    def reload_hive(self) -> HiveTree:
        self._hive = load_hive(self.agents_dir)
        return self._hive

    def is_empty(self) -> bool:
        """True if no queen exists yet (agents/ only has root AGENT.md)."""
        hive = self._get_hive()
        return hive.queen is None

    def start(self, user_request: str) -> TaskRecord:
        """Create a task record for the given user request."""
        return self._task_manager.create_task(user_request)

    def get_queen_context(self, task: TaskRecord) -> dict:
        hive = self._get_hive()
        queen = hive.queen
        return {
            "task_id": task.task_id,
            "task_name": task.name,
            "task_slug": task.slug,
            "started_at": task.created_at,
            "hive_tree": hive.pretty_print(),
            "queen_node": queen,
            "all_agents": hive.all_agents,
            "tasks_dir": str(self.tasks_dir),
            "agents_dir": str(self.agents_dir),
        }

    def queen_system_prompt(self, task: TaskRecord) -> str:
        hive = self._get_hive()
        queen = hive.queen
        base_prompt = ""
        if queen and queen.system_prompt:
            base_prompt = queen.system_prompt + "\n\n"

        ctx = self.get_queen_context(task)
        suffix = _DEFAULT_QUEEN_PROMPT_SUFFIX.format(
            hive_tree=ctx["hive_tree"],
            task_id=task.task_id,
            task_name=task.name,
            started_at=task.created_at,
        )
        return base_prompt + suffix

    @property
    def task_manager(self) -> HiveTaskManager:
        return self._task_manager
