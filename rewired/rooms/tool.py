from __future__ import annotations
from typing import Any, Dict, Optional
from .manager import RoomManager
from .room import MessageStatus

ROOM_TOOL_SCHEMA: Dict[str, Any] = {
    "name": "hive_room",
    "description": (
        "Post or read messages in a hive communication room. "
        "Use this to coordinate with other agents at the same level."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["post", "read", "reply", "update_status", "search"],
            },
            "room_id": {"type": "string"},
            "content": {"type": "string"},
            "parent_id": {"type": "string"},
            "message_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["open", "in_progress", "done", "flagged"],
            },
            "task_id": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["action", "room_id"],
    },
}


async def handle_room_tool(
    action: str,
    room_id: str,
    manager: RoomManager,
    sender: str,
    content: Optional[str] = None,
    parent_id: Optional[str] = None,
    message_id: Optional[str] = None,
    status: Optional[str] = None,
    task_id: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    **_: Any,
) -> Dict[str, Any]:
    try:
        room = manager.get_room(room_id)
        if action == "post":
            if not content:
                return {"error": "content required"}
            m = room.post(sender, content, task_id=task_id)
            return {"message_id": m.id, "created_at": m.created_at.isoformat()}
        elif action == "reply":
            if not content or not parent_id:
                return {"error": "content and parent_id required"}
            m = room.post(sender, content, parent_id=parent_id, task_id=task_id)
            return {
                "message_id": m.id,
                "thread": [
                    {"sender": t.sender, "content": t.content,
                     "created_at": t.created_at.isoformat()}
                    for t in room.get_thread(parent_id)
                ],
            }
        elif action == "read":
            msgs = room.get_messages(limit=limit, task_id=task_id)
            return {
                "messages": [
                    {"id": m.id, "sender": m.sender, "content": m.content,
                     "status": m.status.value, "created_at": m.created_at.isoformat()}
                    for m in msgs
                ]
            }
        elif action == "update_status":
            if not message_id or not status:
                return {"error": "message_id and status required"}
            updated = room.update_status(message_id, MessageStatus(status))
            return {"updated": bool(updated),
                    "status": updated.status.value if updated else None}
        elif action == "search":
            if not query:
                return {"error": "query required"}
            results = room.search(query, limit)
            return {"results": [{"id": m.id, "sender": m.sender,
                                  "content": m.content[:200]} for m in results]}
        return {"error": f"unknown action: {action}"}
    except Exception as exc:
        return {"error": str(exc)}
