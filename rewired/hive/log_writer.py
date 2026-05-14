from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional


def write_log_from_session(
    tasks_dir: Path,
    task_id: str,
    agent_path: str,
    session_data: dict,
    append: bool = True,
) -> str:
    parts = task_id.split("/", 1)
    if len(parts) != 2:
        return f"Invalid task_id: {task_id}"
    date_dir, slug = parts
    log_dir = tasks_dir / date_dir / slug / agent_path
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "LOG.md"

    messages = session_data.get("messages", [])
    model = session_data.get("model", "unknown")
    session_id = session_data.get("session_id", "unknown")
    session_start = session_data.get("session_start", "")

    tool_calls = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "assistant" and "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                tool_calls.append({
                    "name": tc.get("function", {}).get("name", tc.get("name", "?")),
                    "timestamp": msg.get("timestamp", ""),
                })
        elif role == "tool":
            if tool_calls:
                tool_calls[-1]["result_len"] = len(msg.get("content", ""))
                is_err = msg.get("content", "").startswith("Error")
                tool_calls[-1]["status"] = "error" if is_err else "success"

    total = len(tool_calls)
    success_n = sum(1 for t in tool_calls if t.get("status") == "success")
    error_n = sum(1 for t in tool_calls if t.get("status") == "error")

    lines = [
        f"# Log: {task_id} / {agent_path}",
        "",
        f"## Session: {session_id}",
        f"- Model: {model}",
        f"- Started: {session_start[:19] if session_start else 'N/A'}",
        f"- Tool calls: {total} ({success_n} success, {error_n} error)",
        "",
        "## Tool Calls",
        "| # | Tool | Status |",
        "|---|------|--------|",
    ]

    for i, tc in enumerate(tool_calls, 1):
        status = tc.get("status", "?")
        lines.append(f"| {i} | `{tc['name']}` | {status} |")

    if error_n > 0:
        lines.extend(["", "## Errors"])
        for tc in tool_calls:
            if tc.get("status") == "error":
                lines.append(f"- `{tc['name']}` failed")

    content = "\n".join(lines) + "\n"

    mode = "a" if append and log_path.exists() else "w"
    with log_path.open(mode, encoding="utf-8") as f:
        if mode == "a":
            f.write("\n")
        f.write(content)

    return f"LOG.md written ({total} tool calls)"


def write_log_from_db(
    tasks_dir: Path,
    task_id: str,
    agent_path: str,
    session_id: str,
) -> str:
    session_path = (
        Path.home() / ".hermes" / "sessions" / f"session_{session_id}.json"
    )
    if not session_path.exists():
        return f"Session file not found: {session_path}"

    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"Failed to read session: {e}"

    return write_log_from_session(tasks_dir, task_id, agent_path, data)
