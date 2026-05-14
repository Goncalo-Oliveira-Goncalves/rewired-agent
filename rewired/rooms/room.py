from __future__ import annotations
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS messages ("
    "id TEXT PRIMARY KEY,"
    "room_id TEXT NOT NULL,"
    "sender TEXT NOT NULL,"
    "content TEXT NOT NULL,"
    "status TEXT NOT NULL DEFAULT 'open',"
    "parent_id TEXT,"
    "task_id TEXT,"
    "created_at TEXT NOT NULL,"
    "updated_at TEXT NOT NULL,"
    "metadata TEXT NOT NULL DEFAULT '{}'"
    ");"
    "CREATE INDEX IF NOT EXISTS idx_room_created ON messages(room_id,created_at);"
    "CREATE INDEX IF NOT EXISTS idx_task ON messages(task_id);"
    "CREATE INDEX IF NOT EXISTS idx_parent ON messages(parent_id);"
)


class MessageStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FLAGGED = "flagged"


@dataclass
class Message:
    id: str
    room_id: str
    sender: str
    content: str
    status: MessageStatus
    created_at: datetime
    updated_at: datetime
    parent_id: Optional[str] = None
    task_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def _from_row(cls, row) -> "Message":
        return cls(
            id=row[0], room_id=row[1], sender=row[2], content=row[3],
            status=MessageStatus(row[4]), parent_id=row[5], task_id=row[6],
            created_at=datetime.fromisoformat(row[7]),
            updated_at=datetime.fromisoformat(row[8]),
            metadata=json.loads(row[9]),
        )


class Room:
    def __init__(self, room_id: str, db_path: Path) -> None:
        self.room_id = room_id
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), check_same_thread=False)

    def post(self, sender: str, content: str, parent_id: str = None,
             task_id: str = None, metadata: dict = None) -> Message:
        now = datetime.utcnow().isoformat()
        mid = str(uuid.uuid4())
        with self._conn() as c:
            c.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)",
                (mid, self.room_id, sender, content, "open",
                 parent_id, task_id, now, now, json.dumps(metadata or {})),
            )
        return Message(mid, self.room_id, sender, content, MessageStatus.OPEN,
                       datetime.fromisoformat(now), datetime.fromisoformat(now),
                       parent_id, task_id, metadata or {})

    def get_messages(self, limit: int = 50, since: datetime = None,
                     task_id: str = None) -> List[Message]:
        q = ("SELECT id,room_id,sender,content,status,parent_id,task_id,"
             "created_at,updated_at,metadata FROM messages "
             "WHERE room_id=? AND parent_id IS NULL")
        p: list = [self.room_id]
        if since:
            q += " AND created_at > ?"
            p.append(since.isoformat())
        if task_id:
            q += " AND task_id=?"
            p.append(task_id)
        q += " ORDER BY created_at DESC LIMIT ?"
        p.append(limit)
        with self._conn() as c:
            rows = c.execute(q, p).fetchall()
        return [Message._from_row(r) for r in rows]

    def get_thread(self, parent_id: str) -> List[Message]:
        q = ("SELECT id,room_id,sender,content,status,parent_id,task_id,"
             "created_at,updated_at,metadata FROM messages "
             "WHERE parent_id=? ORDER BY created_at ASC")
        with self._conn() as c:
            rows = c.execute(q, (parent_id,)).fetchall()
        return [Message._from_row(r) for r in rows]

    def update_status(self, message_id: str, status: MessageStatus) -> Optional[Message]:
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            c.execute("UPDATE messages SET status=?,updated_at=? WHERE id=?",
                      (status.value, now, message_id))
            row = c.execute(
                "SELECT id,room_id,sender,content,status,parent_id,task_id,"
                "created_at,updated_at,metadata FROM messages WHERE id=?",
                (message_id,),
            ).fetchone()
        return Message._from_row(row) if row else None

    def search(self, query_str: str, limit: int = 20) -> List[Message]:
        q = ("SELECT id,room_id,sender,content,status,parent_id,task_id,"
             "created_at,updated_at,metadata FROM messages "
             "WHERE room_id=? AND content LIKE ? ORDER BY created_at DESC LIMIT ?")
        with self._conn() as c:
            rows = c.execute(q, (self.room_id, f"%{query_str}%", limit)).fetchall()
        return [Message._from_row(r) for r in rows]

    def purge_old_messages(self, before: datetime) -> int:
        with self._conn() as c:
            c.execute("DELETE FROM messages WHERE room_id=? AND created_at < ?",
                      (self.room_id, before.isoformat()))
            count = c.rowcount
        return count

    def message_count(self) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM messages WHERE room_id=?", (self.room_id,)
            ).fetchone()
        return row[0] if row else 0
