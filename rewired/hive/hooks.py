from __future__ import annotations
import json
from pathlib import Path
from typing import Optional


_TASKS_DIR = Path.home() / ".rewired" / "tasks"


def log_session_to_task(
    session_id: str,
    task_id: str,
    agent_path: str = "queen-bee",
    tasks_dir: Optional[Path] = None,
) -> str:
    from .log_writer import write_log_from_db

    td = tasks_dir or _TASKS_DIR
    return write_log_from_db(td, task_id, agent_path, session_id)


def log_latest_session_to_task(
    task_id: str,
    agent_path: str = "queen-bee",
    tasks_dir: Optional[Path] = None,
    sessions_dir: Optional[Path] = None,
) -> str:
    sd = sessions_dir or Path.home() / ".hermes" / "sessions"
    td = tasks_dir or _TASKS_DIR

    session_files = sorted(sd.glob("session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not session_files:
        return "No session files found"

    from .log_writer import write_log_from_session
    try:
        data = json.loads(session_files[0].read_text(encoding="utf-8"))
    except Exception as e:
        return f"Failed to read {session_files[0].name}: {e}"

    return write_log_from_session(td, task_id, agent_path, data)
