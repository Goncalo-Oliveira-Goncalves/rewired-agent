from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class AgentStatus:
    phase: str = "idle"
    message: str = ""
    tool_name: str = ""
    progress_pct: int = 0
    tool_call_count: int = 0
    updated_at: str = ""


_STATUS_FILE = "status.json"


def _task_dir(tasks_dir: Path, task_id: str) -> Path:
    parts = task_id.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid task_id: {task_id}")
    return tasks_dir / parts[0] / parts[1]


def _agent_dir(tasks_dir: Path, task_id: str, agent_path: str) -> Path:
    return _task_dir(tasks_dir, task_id) / agent_path


def read_status(
    tasks_dir: Path,
    task_id: str,
    agent_path: str = "queen-bee",
) -> Optional[AgentStatus]:
    sp = _agent_dir(tasks_dir, task_id, agent_path) / _STATUS_FILE
    if not sp.exists():
        return None
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        return AgentStatus(**data)
    except Exception:
        return None


def write_status(
    tasks_dir: Path,
    task_id: str,
    agent_path: str,
    status: AgentStatus,
) -> None:
    status.updated_at = datetime.utcnow().isoformat()
    sp = _agent_dir(tasks_dir, task_id, agent_path) / _STATUS_FILE
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(asdict(status), indent=2), encoding="utf-8")


def read_log_tail(
    tasks_dir: Path,
    task_id: str,
    agent_path: str = "queen-bee",
    n_lines: int = 40,
) -> list[str]:
    lp = _agent_dir(tasks_dir, task_id, agent_path) / "LOG.md"
    if not lp.exists():
        return []
    try:
        text = lp.read_text(encoding="utf-8")
        lines = text.rstrip("\n").split("\n")
        return lines[-n_lines:]
    except Exception:
        return []


_STATUS_RE = re.compile(
    r'\[STATUS\]\s+'
    r'phase=(\w+)\s+'
    r'msg="([^"]*)"\s+'
    r'pct=(\d+)\s+'
    r'tools=(\d+)'
)

_TOOL_LOG_RE = re.compile(r'^(\|.*?`([^`]+)`.*?)$', re.MULTILINE)


def parse_status_markers(lines: list[str]) -> Optional[AgentStatus]:
    for line in reversed(lines):
        m = _STATUS_RE.search(line)
        if m:
            return AgentStatus(
                phase=m.group(1),
                message=m.group(2),
                progress_pct=int(m.group(3)),
                tool_call_count=int(m.group(4)),
            )
    return None
