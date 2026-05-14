from pathlib import Path

_AGENTS_DIR = Path.home() / ".rewired" / "agents"


def _hive_available() -> bool:
    return _AGENTS_DIR.exists()


def hive_home() -> Path:
    return Path.home() / ".rewired"


def hive_tasks_dir() -> Path:
    return hive_home() / "tasks"


def hive_rooms_dir() -> Path:
    return hive_home() / "rooms"
