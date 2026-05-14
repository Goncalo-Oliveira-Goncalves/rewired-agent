from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, date
from enum import Enum
from pathlib import Path
from typing import List, Optional


class TaskStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass
class TaskRecord:
    task_id: str
    name: str
    slug: str
    status: TaskStatus
    created_at: str        # ISO 8601
    date_dir: str          # YYYY-MM-DD
    estimated_done: Optional[str] = None
    report: Optional[str] = None
    initiator: str = "user"

    @property
    def task_dir(self) -> str:
        return f"{self.date_dir}/{self.slug}"


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:60] or "task"


class HiveTaskManager:
    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = Path(tasks_dir)

    def _today(self) -> str:
        return date.today().strftime("%Y-%m-%d")

    def _unique_slug(self, base_slug: str, date_dir: str) -> str:
        day_dir = self.tasks_dir / date_dir
        slug = base_slug
        counter = 2
        while (day_dir / slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

    def _meta_path(self, task: TaskRecord) -> Path:
        return self.tasks_dir / task.date_dir / task.slug / "meta.json"

    def _save_meta(self, task: TaskRecord) -> None:
        meta_path = self._meta_path(task)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(asdict(task), indent=2), encoding="utf-8")

    def create_task(self, name: str, initiator: str = "user") -> TaskRecord:
        date_dir = self._today()
        base_slug = _slugify(name)
        slug = self._unique_slug(base_slug, date_dir)
        task_id = f"{date_dir}/{slug}"
        task = TaskRecord(
            task_id=task_id,
            name=name,
            slug=slug,
            status=TaskStatus.IN_PROGRESS,
            created_at=datetime.utcnow().isoformat(),
            date_dir=date_dir,
            initiator=initiator,
        )
        self._save_meta(task)
        return task

    def _agent_dir(self, task: TaskRecord, agent_path: str) -> Path:
        # agent_path like "queen-bee" or "queen-bee/general-dev"
        return self.tasks_dir / task.date_dir / task.slug / agent_path

    def write_log(self, task: TaskRecord, agent_path: str, content: str, append: bool = True) -> None:
        log_path = self._agent_dir(task, agent_path) / "LOG.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append and log_path.exists() else "w"
        with log_path.open(mode, encoding="utf-8") as f:
            if mode == "a":
                f.write("\n")
            f.write(content)

    def write_report(self, task: TaskRecord, agent_path: str, content: str) -> None:
        report_path = self._agent_dir(task, agent_path) / "REPORT.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(content, encoding="utf-8")

    def set_status(self, task: TaskRecord, status: TaskStatus) -> None:
        task.status = status
        self._save_meta(task)

    def set_estimated_done(self, task: TaskRecord, dt: datetime) -> None:
        task.estimated_done = dt.isoformat()
        self._save_meta(task)

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        # task_id is "YYYY-MM-DD/slug"
        parts = task_id.split("/", 1)
        if len(parts) != 2:
            return None
        date_dir, slug = parts
        meta_path = self.tasks_dir / date_dir / slug / "meta.json"
        if not meta_path.exists():
            return None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["status"] = TaskStatus(data["status"])
        return TaskRecord(**data)

    def list_tasks(self, for_date: Optional[str] = None) -> List[TaskRecord]:
        target = for_date or self._today()
        day_dir = self.tasks_dir / target
        if not day_dir.exists():
            return []
        tasks = []
        for slug_dir in sorted(day_dir.iterdir()):
            meta = slug_dir / "meta.json"
            if meta.exists():
                try:
                    data = json.loads(meta.read_text(encoding="utf-8"))
                    data["status"] = TaskStatus(data["status"])
                    tasks.append(TaskRecord(**data))
                except Exception:
                    continue
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def get_report(self, task: TaskRecord, agent_path: str = "queen-bee") -> str:
        report_path = self._agent_dir(task, agent_path) / "REPORT.md"
        if report_path.exists():
            return report_path.read_text(encoding="utf-8")
        return ""
