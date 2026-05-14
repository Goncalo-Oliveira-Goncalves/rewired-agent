import json
from pathlib import Path

from tools.registry import registry
from tools.hive_common import hive_tasks_dir, _hive_available


def handle_set_status(task_id: str, status: str, **kwargs) -> str:
    try:
        from rewired.hive.task_manager import HiveTaskManager, TaskStatus
        tm = HiveTaskManager(hive_tasks_dir())
        task = tm.get_task(task_id)
        if not task:
            return json.dumps({"success": False, "error": f"Task not found: {task_id}"})
        tm.set_status(task, TaskStatus(status))
        return json.dumps({"success": True, "task_id": task_id, "status": status})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


_STATUS_SCHEMA = {
    "name": "hive_set_task_status",
    "description": "Mark a task as DONE or FAILED in the hive task manager",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID in format YYYY-MM-DD/slug",
            },
            "status": {
                "type": "string",
                "enum": ["DONE", "FAILED"],
                "description": "New status for the task",
            },
        },
        "required": ["task_id", "status"],
    },
}

registry.register(
    name="hive_set_task_status",
    toolset="hive",
    schema=_STATUS_SCHEMA,
    handler=lambda args, h=handle_set_status: h(**args),
    check_fn=_hive_available,
    emoji="🐝",
)


def handle_write_status(
    task_id: str,
    phase: str = "thinking",
    message: str = "",
    tool_name: str = "",
    progress_pct: int = 0,
    tool_call_count: int = 0,
    agent_path: str = "queen-bee",
    **kwargs,
) -> str:
    try:
        from rewired.hive.status import AgentStatus, write_status
        status = AgentStatus(
            phase=phase,
            message=message,
            tool_name=tool_name,
            progress_pct=progress_pct,
            tool_call_count=tool_call_count,
        )
        write_status(hive_tasks_dir(), task_id, agent_path, status)
        return json.dumps({"success": True, "task_id": task_id, "phase": phase})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


_WRITE_STATUS_SCHEMA = {
    "name": "hive_write_status",
    "description": "Report the current agent's progress, phase, and thinking to the hive task inspector. Call this to show what you are doing in real-time.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID in format YYYY-MM-DD/slug",
            },
            "phase": {
                "type": "string",
                "enum": ["thinking", "running_tool", "idle", "complete", "error"],
                "description": "Current phase of the agent's work",
            },
            "message": {
                "type": "string",
                "description": "Human-readable description of what the agent is currently doing",
            },
            "tool_name": {
                "type": "string",
                "description": "Name of the tool currently being called (if any)",
            },
            "progress_pct": {
                "type": "integer",
                "description": "Estimated progress percentage (0-100)",
                "minimum": 0,
                "maximum": 100,
            },
            "tool_call_count": {
                "type": "integer",
                "description": "Total tool calls made so far",
            },
            "agent_path": {
                "type": "string",
                "description": "Agent path within the task (default: queen-bee)",
            },
        },
        "required": ["task_id"],
    },
}

registry.register(
    name="hive_write_status",
    toolset="hive",
    schema=_WRITE_STATUS_SCHEMA,
    handler=lambda args, h=handle_write_status: h(**args),
    check_fn=_hive_available,
    emoji="🐝",
)
