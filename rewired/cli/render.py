from __future__ import annotations
import datetime
import re
import time as _time
from pathlib import Path
from typing import List, Optional

from prompt_toolkit.styles import Style

from rewired.hive.status import AgentStatus

_STYLE = Style([
    ("title", "bold #ffcc00"),
    ("status-active", "bold #00ff88"),
    ("status-done", "bold #44cc44"),
    ("status-failed", "bold #ff4444"),
    ("selected", "reverse"),
    ("muted", "#666666"),
    ("sep", "#444444"),
    ("phase", "bold #00ccff"),
    ("tool-count", "#ff8800"),
    ("log-tool", "#8888ff"),
    ("log-status", "#00ff88"),
    ("log-think", "#ffcc00"),
    ("log-msg", "#cccccc"),
    ("context-label", "bold #ffcc00"),
    ("feedback", "bold #ffcc00"),
    ("bar-fill", "#00ff88"),
    ("bar-empty", "#333333"),
])

_ICON = {"IN_PROGRESS": "●", "DONE": "✓", "FAILED": "✗"}
_PHASE_ICON = {"thinking": "🧠", "running_tool": "⚡", "idle": "○", "complete": "✓", "error": "✗"}

_S = "  "  # standard indent


def _time_ago(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        now = datetime.datetime.now(dt.tzinfo) if dt.tzinfo else datetime.datetime.now()
        mins = int((now - dt).total_seconds() / 60)
        if mins < 1:
            return "just now"
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        return f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"
    except Exception:
        return iso_str[:16]


def _bar(pct: int, w: int = 15) -> str:
    f = max(0, min(w, round(pct / 100 * w)))
    return ("class:bar-fill", "▓" * f), ("class:bar-empty", "░" * (w - f))


def _hline() -> List[tuple]:
    return [("class:sep", f"  {'─' * 56}\n")]


def render_list(
    tasks: List[dict],
    sel: int,
    feedback: str,
    feedback_until: float,
    report_cache: dict[str, str],
    filter_date: Optional[str],
) -> List[tuple]:
    lines: List[tuple] = []

    lines += [("class:title", f"\n{'  ⚡ re:wired'}")]
    lines += [("", f"  ·  {len(tasks)} tasks")]
    if filter_date:
        lines += [("class:muted", f"  [{filter_date}]")]
    lines += [("", "\n")]

    if _time.time() < feedback_until and feedback:
        lines += [("class:feedback", f"  {feedback}\n")]
    else:
        lines += [("class:muted", f"  [↑↓ ↵ select  /cmd  F5 refresh  ^C quit]\n")]

    lines += _hline()

    if not tasks:
        lines += [("class:muted", f"\n{_S}No tasks — type a request below\n\n")]
        return lines

    for i, t in enumerate(tasks[:20]):
        st = t.get("status", "IN_PROGRESS")
        icon = _ICON.get(st, "?")
        slug = t.get("slug", "?")
        est = t.get("estimated_done", "")
        right = f"est. {est[:16]}" if est else _time_ago(t.get("created_at", ""))
        sc = "class:selected" if i == sel else ""
        mk = "▸" if i == sel else " "
        sc2 = "class:selected" if i == sel else f"class:status-{st.lower()}"

        lines += [(sc, f"  {mk} "), (sc2, f"{icon} {slug:<42} {st:<12}"), ("class:muted" if not sc else "", f"{right}\n")]

        preview = report_cache.get(slug, "")
        if preview:
            lines += [("class:muted" if not sc else "class:selected", f"     │ {preview[:68]}\n")]

        # Show an inline micro progress bar if IN_PROGRESS
        if st == "IN_PROGRESS":
            lines += [("", "\n")]

    lines += [("", "\n")]
    return lines


def _log_line_style(line: str) -> str:
    s = line.strip()
    if re.match(r"\[TOOL\]|^│.*`", s):
        return "class:log-tool"
    if "[STATUS]" in s:
        return "class:log-status"
    if re.match(r"\[THINK\]|⚡|🧠|> \*\*", s):
        return "class:log-think"
    return ""


def render_detail(
    task: Optional[dict],
    tasks_dir: Path,
    status: Optional[AgentStatus],
    log_lines: List[str],
    log_scroll: int,
) -> List[tuple]:
    if not task:
        return [("class:selected", f"\n{_S}No task selected\n")]

    st = task.get("status", "IN_PROGRESS")
    icon = _ICON.get(st, "?")
    slug = task.get("slug", "?")
    name = task.get("name", slug)
    ts = task.get("created_at", "")[:16]
    task_dir = tasks_dir / task.get("date_dir", "") / slug
    tid = task.get("task_id", "")

    lines: List[tuple] = []

    # Header bar
    lines += [("class:title", f"\n  ┌─ {name}\n")]
    lines += [("", f"  │")]
    lines += [(f"class:status-{st.lower()}", f" {icon} {st}")]
    lines += [("class:muted", f"  │  {ts}")]
    lines += [("class:muted", f"  │  {tid}")]
    lines += [("", "\n")]

    # Agent status section
    if st == "IN_PROGRESS":
        lines += [("class:muted", f"  ├ 🐝 Queen Bee\n")]

        if status:
            pct = status.progress_pct or 0
            phase = status.phase or "idle"
            msg = status.message or ""
            tools = status.tool_call_count or 0
            picon = _PHASE_ICON.get(phase, "●")
            bf, be = _bar(pct)

            # Progress bar row
            lines += [("", f"  │ "), bf, be,
                      ("", f"  {pct}%"),
                      ("class:phase", f"  {picon} {phase}"),
                      ("", "  "),
                      ("class:tool-count", f"{tools} tools"),
                      ("", "\n")]
            if msg:
                lines += [("class:log-msg", f"  │ {msg}\n")]
        else:
            lines += [("class:muted", f"  │ No status yet\n")]

        lines += _hline()

    # Live feed
    lines += [("class:muted", f"  ├ Feed\n")]
    if log_lines:
        total = len(log_lines)
        start = max(0, total - 15 - log_scroll)
        end = max(start, total - log_scroll)
        start = max(0, end - 15)

        for line in log_lines[start:end]:
            sty = _log_line_style(line)
            lines += [(sty, f"  │ {line}\n")]

        if total > end - start:
            lines += [("class:muted", f"  │ ({total} lines · ↑↓ scroll)\n")]
        else:
            lines += [("class:muted", f"  │\n")]
    else:
        lines += [("class:muted", f"  │ (waiting for log output...)\n")]
        lines += [("class:muted", f"  │\n")]

    # Agent dirs
    agent_dirs = sorted([p for p in task_dir.iterdir() if p.is_dir()], key=lambda p: p.name)
    if agent_dirs:
        lines += [("class:muted", f"  ├ Agents\n")]
        for ad in agent_dirs:
            has = "✓" if (ad / "REPORT.md").exists() else "●"
            lines += [("class:muted", f"  │ {has} {ad.name}\n")]

    # REPORT
    qr = task_dir / "queen-bee" / "REPORT.md"
    if qr.exists():
        text = qr.read_text().strip()
        lines += [("class:muted", f"  ├ Report\n")]
        displayed = 0
        for line in text.split("\n"):
            if line.strip() and displayed < 8:
                lines += [("class:log-msg", f"  │ {line}\n")]
                displayed += 1
        if len(text.split("\n")) > 8:
            lines += [("class:muted", f"  │ (...)\n")]

    # Bottom
    lines += [("", f"  └{'─' * 56}\n")]
    lines += [("class:muted", f"  [Esc back  ↑↓ scroll  F5 refresh  type + ↵ send context  ^C quit]\n")]
    return lines
