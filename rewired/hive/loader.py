from __future__ import annotations
import yaml
from pathlib import Path
from typing import Optional

from .schema import AgentNode, HiveTree


def _parse_agent_md(md_path: Path) -> dict:
    """Parse an AGENT.md file — YAML frontmatter + system_prompt body."""
    text = md_path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    data: dict = {}
    system_prompt = ""
    if len(parts) >= 3:
        try:
            data = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            data = {}
        system_prompt = parts[2].strip()
    elif len(parts) == 1:
        system_prompt = parts[0].strip()
    data["_system_prompt"] = system_prompt
    return data


def _walk(folder: Path, parent: AgentNode, level: int) -> None:
    """Recursively populate parent's children from sub-folders."""
    try:
        entries = sorted(folder.iterdir())
    except PermissionError:
        return

    for entry in entries:
        if not entry.is_dir():
            continue
        agent_md_path = entry / "AGENT.md"
        is_team = not agent_md_path.exists()

        if is_team:
            node = AgentNode(
                name=entry.name,
                path=entry,
                agent_md={},
                level=level,
                is_team=True,
            )
        else:
            agent_md = _parse_agent_md(agent_md_path)
            name = agent_md.get("name", entry.name)
            node = AgentNode(
                name=name,
                path=entry,
                agent_md=agent_md,
                level=level,
                is_team=False,
            )

        parent.add_child(node)
        _walk(entry, node, level + 1)


def load_hive(agents_dir: Path) -> HiveTree:
    """Build a HiveTree from the agents/ directory.

    agents_dir: path to the agents/ folder (contains root AGENT.md + sub-folders)
    """
    agents_dir = Path(agents_dir).resolve()

    root_md_path = agents_dir / "AGENT.md"
    root_md: dict = {}
    if root_md_path.exists():
        root_md = _parse_agent_md(root_md_path)

    root = AgentNode(
        name=root_md.get("name", "hive"),
        path=agents_dir,
        agent_md=root_md,
        level=0,
        is_team=False,
    )

    _walk(agents_dir, root, level=1)

    return HiveTree(root=root)
