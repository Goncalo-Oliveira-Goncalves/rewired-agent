from __future__ import annotations
import datetime
import json
import threading
import time as _time
from pathlib import Path
from typing import List, Optional

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from rewired.cli.render import _STYLE, render_list, render_detail
from rewired.hive.status import AgentStatus, read_status, read_log_tail
from rewired.hive.task_manager import HiveTaskManager, TaskStatus
from tools.hive_common import hive_tasks_dir


def _slugify(text: str) -> str:
    import re
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")[:60] or "task"


def _load_tasks(tasks_dir: Path) -> List[dict]:
    out = []
    for p in tasks_dir.glob("*/*/meta.json"):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            pass
    out.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return out


def _load_reports(tasks_dir: Path, tasks: List[dict]) -> dict[str, str]:
    cache = {}
    for t in tasks:
        slug = t.get("slug", "")
        if not slug:
            continue
        rp = tasks_dir / t.get("date_dir", "") / slug / "queen-bee" / "REPORT.md"
        if rp.exists():
            try:
                first = rp.read_text().split("\n")[0].strip()
                if first:
                    cache[slug] = first
            except Exception:
                pass
    return cache


_AUTO_REFRESH_SECS = 30
_DETAIL_REFRESH_SECS = 5
_FEEDBACK_DURATION = 5
_LOG_VISIBLE_LINES = 15


class RewiredFeed:
    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = Path(tasks_dir)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._task_manager = HiveTaskManager(self.tasks_dir)
        self._tasks: List[dict] = []
        self._selected_index = 0
        self._mode = "list"
        self._detail_task: Optional[dict] = None
        self._filter_date: Optional[str] = None
        self._feedback = ""
        self._feedback_until = 0.0
        self._report_cache: dict[str, str] = {}
        self._agent_status: Optional[AgentStatus] = None
        self._log_lines: List[str] = []
        self._log_scroll = 0
        self._detail_task_id: Optional[str] = None
        self.refresh()

    def _resolve_task_id(self, task: dict) -> str:
        return task.get("task_id", f"{task.get('date_dir', '')}/{task.get('slug', '')}")

    def refresh(self) -> None:
        self._tasks = _load_tasks(self.tasks_dir)
        self._report_cache = _load_reports(self.tasks_dir, self._tasks)
        if self._filter_date:
            self._tasks = [t for t in self._tasks if t.get("date_dir") == self._filter_date]
        if self._tasks:
            self._selected_index = min(self._selected_index, len(self._tasks) - 1)
        else:
            self._selected_index = 0

        if self._mode == "detail" and self._detail_task_id:
            self._load_detail_data()

    def _load_detail_data(self) -> None:
        if not self._detail_task_id:
            return
        tid = self._detail_task_id
        self._agent_status = read_status(self.tasks_dir, tid, "queen-bee")
        self._log_lines = read_log_tail(self.tasks_dir, tid, "queen-bee", n_lines=80)
        self._log_scroll = min(self._log_scroll, max(0, len(self._log_lines) - _LOG_VISIBLE_LINES))

    def _set_feedback(self, msg: str) -> None:
        self._feedback = msg
        self._feedback_until = _time.time() + _FEEDBACK_DURATION

    def submit_task(self, name: str) -> str:
        slug = _slugify(name)
        date_dir = datetime.date.today().strftime("%Y-%m-%d")
        base, n = slug, 2
        while (self.tasks_dir / date_dir / slug).exists():
            slug = f"{base}-{n}"
            n += 1
        task_dir = self.tasks_dir / date_dir / slug
        task_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "task_id": f"{date_dir}/{slug}",
            "name": name,
            "slug": slug,
            "status": "IN_PROGRESS",
            "created_at": datetime.datetime.utcnow().isoformat(),
            "date_dir": date_dir,
            "initiator": "user",
        }
        (task_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        self.refresh()
        self._set_feedback(f"Task created: {slug}")
        return slug

    def _send_context(self, text: str) -> None:
        if not self._detail_task_id:
            return
        from rewired.hive.status import write_status
        parts = self._detail_task_id.split("/", 1)
        if len(parts) != 2:
            return
        date_dir, slug = parts
        ctx_dir = self.tasks_dir / date_dir / slug / "queen-bee"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        ctx_path = ctx_dir / "CONTEXT.md"
        entry = f"> **Context from user** ({datetime.datetime.utcnow().isoformat()[:19]})\n\n{text.strip()}\n\n"
        if ctx_path.exists():
            ctx_path.write_text(ctx_path.read_text(encoding="utf-8") + entry, encoding="utf-8")
        else:
            ctx_path.write_text(entry, encoding="utf-8")

        # Also write a status marker so the agent sees new context
        write_status(
            self.tasks_dir,
            self._detail_task_id,
            "queen-bee",
            AgentStatus(
                phase="thinking",
                message=f"Context received from user",
                tool_call_count=self._agent_status.tool_call_count if self._agent_status else 0,
                progress_pct=self._agent_status.progress_pct if self._agent_status else 0,
            ),
        )
        self._load_detail_data()
        self._set_feedback(f"Context sent to queen-bee")

    def _handle_command(self, text: str, event) -> None:
        parts = text[1:].strip().split()
        if not parts:
            return
        verb = parts[0].lower()
        args = parts[1:]

        if verb in ("help", "h", "?"):
            self._set_feedback("/help  /refresh  /today  /all  /cancel <slug>  /status <slug>")
        elif verb in ("refresh", "r"):
            self.refresh()
            self._set_feedback(f"Refreshed — {len(self._tasks)} tasks")
        elif verb == "today":
            self._filter_date = datetime.date.today().strftime("%Y-%m-%d")
            self.refresh()
            self._set_feedback(f"Today — {len(self._tasks)} tasks")
        elif verb == "all":
            self._filter_date = None
            self.refresh()
            self._set_feedback(f"All — {len(self._tasks)} tasks")
        elif verb in ("cancel", "x"):
            slug = args[0] if args else ""
            found = next((t for t in self._tasks if t.get("slug") == slug or t["task_id"].endswith(slug)), None)
            if found:
                task = self._task_manager.get_task(found["task_id"])
                if task:
                    self._task_manager.set_status(task, TaskStatus.FAILED)
                    self.refresh()
                    self._set_feedback(f"Cancelled: {slug}")
            else:
                self._set_feedback(f"Not found: {slug}")
        elif verb in ("status", "s"):
            slug = args[0] if args else ""
            for t in self._tasks:
                if t.get("slug") == slug or t["task_id"].endswith(slug):
                    self._selected_index = self._tasks.index(t)
                    self._enter_detail(t)
                    break
            else:
                self._set_feedback(f"Not found: {slug}")
        else:
            self._set_feedback(f"Unknown: /{verb}. Try /help")
        event.app.invalidate()

    def _enter_detail(self, task: dict) -> None:
        self._mode = "detail"
        self._detail_task = task
        self._detail_task_id = self._resolve_task_id(task)
        self._log_scroll = 0
        self._load_detail_data()

    def _render(self) -> List[tuple]:
        if self._mode == "detail":
            return render_detail(
                self._detail_task,
                self.tasks_dir,
                self._agent_status,
                self._log_lines,
                self._log_scroll,
            )
        return render_list(
            self._tasks,
            self._selected_index,
            self._feedback,
            self._feedback_until,
            self._report_cache,
            self._filter_date,
        )

    def run(self) -> None:
        input_area = TextArea(prompt="> ", multiline=False, height=1, style="class:context-prompt")
        kb = KeyBindings()

        @kb.add("up")
        def _up(event) -> None:
            if self._mode == "list" and self._tasks:
                self._selected_index = max(0, self._selected_index - 1)
                event.app.invalidate()
            elif self._mode == "detail" and self._log_lines:
                self._log_scroll = min(
                    self._log_scroll + 1,
                    max(0, len(self._log_lines) - _LOG_VISIBLE_LINES),
                )
                event.app.invalidate()

        @kb.add("down")
        def _down(event) -> None:
            if self._mode == "list" and self._tasks:
                self._selected_index = min(len(self._tasks) - 1, self._selected_index + 1)
                event.app.invalidate()
            elif self._mode == "detail" and self._log_scroll > 0:
                self._log_scroll -= 1
                event.app.invalidate()

        @kb.add("enter")
        def _enter(event) -> None:
            txt = input_area.text.strip()
            if self._mode == "detail":
                if txt:
                    self._send_context(txt)
                    input_area.text = ""
                    event.app.invalidate()
                else:
                    self._mode = "list"
                    self._detail_task = None
                    self._detail_task_id = None
                    self._agent_status = None
                    self._log_lines = []
                    self._log_scroll = 0
                    event.app.invalidate()
            elif txt.startswith("/"):
                self._handle_command(txt, event)
                input_area.text = ""
            elif txt:
                self.submit_task(txt)
                input_area.text = ""
                event.app.invalidate()
            elif self._tasks:
                self._enter_detail(self._tasks[self._selected_index])
                event.app.invalidate()

        @kb.add("escape")
        def _escape(event) -> None:
            if self._mode == "detail":
                self._mode = "list"
                self._detail_task = None
                self._detail_task_id = None
                self._agent_status = None
                self._log_lines = []
                self._log_scroll = 0
                event.app.invalidate()

        @kb.add("c-c")
        @kb.add("c-q")
        def _quit(event) -> None:
            event.app.exit()

        @kb.add("f5")
        def _refresh(event) -> None:
            self.refresh()
            self._set_feedback(f"Refreshed — {len(self._tasks)} tasks")
            event.app.invalidate()

        layout = Layout(HSplit([
            Window(content=FormattedTextControl(self._render), dont_extend_height=True),
            input_area,
        ]))

        app = Application(layout=layout, key_bindings=kb, style=_STYLE, full_screen=True)

        def _auto_refresh():
            while True:
                interval = _DETAIL_REFRESH_SECS if self._mode == "detail" else _AUTO_REFRESH_SECS
                _time.sleep(interval)
                self.refresh()
                app.invalidate()

        threading.Thread(target=_auto_refresh, daemon=True).start()
        app.run()
