import json
from pathlib import Path

from tools.registry import registry
from tools.hive_common import hive_rooms_dir, _AGENTS_DIR, _hive_available


def _check_room_access(agent_name: str, room_id: str, action: str) -> str | None:
    from rewired.hive.loader import load_hive
    hive = load_hive(_AGENTS_DIR)
    node = hive.get_by_name(agent_name)
    if not node:
        return f"Unknown agent: {agent_name}"

    is_team_room = room_id.startswith("team-")
    is_generals_room = room_id == "generals"

    if node.role == "soldier":
        return "Soldiers cannot access rooms"

    if node.role == "queen":
        if is_generals_room and action != "read":
            return "Queen can only read the generals room"
        return None

    if node.role == "orchestrator":
        if is_generals_room:
            return None
        if is_team_room:
            expected_team = room_id.replace("team-", "")
            if not any(c for c in node.children if c.name == expected_team) and \
               not node.name.replace("general-", "") == expected_team:
                return f"General {agent_name} does not lead team {expected_team}"
            return None
        return None

    return None


def handle_room(
    action: str,
    room_id: str,
    content: str = None,
    sender: str = None,
    parent_id: str = None,
    message_id: str = None,
    status: str = None,
    task_id: str = None,
    query: str = None,
    limit: int = 20,
    **kwargs,
) -> str:
    try:
        from rewired.rooms.manager import RoomManager
        from rewired.rooms.room import MessageStatus

        agent_name = sender or "unknown"

        access_error = _check_room_access(agent_name, room_id, action)
        if access_error:
            return json.dumps({"error": f"Access denied: {access_error}"})

        rooms_dir = hive_rooms_dir()
        manager = RoomManager(rooms_dir)
        room = manager.get_room(room_id)

        if action == "post":
            if not content:
                return json.dumps({"error": "content required"})
            m = room.post(agent_name, content, task_id=task_id)
            return json.dumps({
                "message_id": m.id,
                "created_at": m.created_at.isoformat(),
            })

        elif action == "reply":
            if not content or not parent_id:
                return json.dumps({"error": "content and parent_id required"})
            m = room.post(agent_name, content, parent_id=parent_id, task_id=task_id)
            thread = [
                {"sender": t.sender, "content": t.content,
                 "created_at": t.created_at.isoformat()}
                for t in room.get_thread(parent_id)
            ]
            return json.dumps({"message_id": m.id, "thread": thread})

        elif action == "read":
            msgs = room.get_messages(limit=limit, task_id=task_id)
            return json.dumps({
                "messages": [
                    {"id": m.id, "sender": m.sender, "content": m.content,
                     "status": m.status.value, "created_at": m.created_at.isoformat()}
                    for m in msgs
                ]
            })

        elif action == "update_status":
            if not message_id or not status:
                return json.dumps({"error": "message_id and status required"})
            updated = room.update_status(message_id, MessageStatus(status))
            return json.dumps({
                "updated": bool(updated),
                "status": updated.status.value if updated else None,
            })

        elif action == "search":
            if not query:
                return json.dumps({"error": "query required"})
            results = room.search(query, limit)
            return json.dumps({
                "results": [
                    {"id": r.id, "sender": r.sender, "content": r.content[:200]}
                    for r in results
                ]
            })

        elif action == "purge":
            from datetime import datetime, timedelta
            days = kwargs.get("days", 30)
            before = datetime.utcnow() - timedelta(days=days)
            count = room.purge_old_messages(before)
            return json.dumps({
                "purged": count,
                "remaining": room.message_count(),
                "before": before.isoformat(),
            })

        return json.dumps({"error": f"unknown action: {action}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


_ROOM_SCHEMA = {
    "name": "hive_room",
    "description": "Post or read messages in a hive communication room. Use this to coordinate with other agents at the same level.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["post", "read", "reply", "update_status", "search", "purge"],
            },
            "room_id": {"type": "string"},
            "content": {"type": "string"},
            "parent_id": {"type": "string"},
            "message_id": {"type": "string"},
            "status": {"type": "string", "enum": ["open", "in_progress", "done", "flagged"]},
            "task_id": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
            "days": {"type": "integer", "default": 30, "description": "Purge messages older than N days"},
        },
        "required": ["action", "room_id", "sender"],
    },
}

registry.register(
    name="hive_room",
    toolset="hive",
    schema=_ROOM_SCHEMA,
    handler=lambda args, h=handle_room: h(**args),
    check_fn=_hive_available,
    emoji="🐝",
)
