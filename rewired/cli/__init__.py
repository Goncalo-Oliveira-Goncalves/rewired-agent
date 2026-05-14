from __future__ import annotations
from pathlib import Path
from typing import Optional

from rewired.cli.app import RewiredFeed
from tools.hive_common import hive_tasks_dir

__all__ = ["RewiredFeed", "run_cli"]


def run_cli(tasks_dir: Optional[Path] = None) -> None:
    if tasks_dir is None:
        tasks_dir = hive_tasks_dir()
    RewiredFeed(tasks_dir).run()
