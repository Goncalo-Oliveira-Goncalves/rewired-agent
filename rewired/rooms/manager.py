from __future__ import annotations
from pathlib import Path
from typing import List
from .room import Room, Message


class RoomManager:
    def __init__(self, rooms_dir: Path) -> None:
        self.rooms_dir = Path(rooms_dir)
        self.rooms_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Room] = {}

    def get_room(self, room_id: str) -> Room:
        if room_id not in self._cache:
            self._cache[room_id] = Room(room_id, self.rooms_dir / f"{room_id}.db")
        return self._cache[room_id]

    def get_generals_room(self) -> Room:
        return self.get_room("generals")

    def get_team_room(self, team_name: str) -> Room:
        safe = team_name.lower().replace(" ", "-").replace("/", "-")
        return self.get_room(f"team-{safe}")

    def list_rooms(self) -> List[str]:
        return [p.stem for p in self.rooms_dir.glob("*.db")]

    def get_all_recent(self, limit: int = 20) -> List[Message]:
        msgs: List[Message] = []
        for rid in self.list_rooms():
            msgs.extend(self.get_room(rid).get_messages(limit=limit))
        msgs.sort(key=lambda m: m.created_at, reverse=True)
        return msgs[:limit]
