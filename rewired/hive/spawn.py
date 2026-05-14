from __future__ import annotations
from pathlib import Path
from typing import Optional

from .loader import load_hive
from .schema import HiveTree


_SPAWN_TEMPLATE = """\
---
name: {name}
version: "1.0"
description: {description}
role: {role}
model: {model}
max_iterations: {max_iterations}
tools:
{toolsets_yaml}
---
{system_prompt}
"""


def _toolsets_yaml(toolsets: list[str]) -> str:
    if not toolsets:
        return "  []"
    return "\n".join(f"  - {t}" for t in toolsets)


def spawn_agent(
    agents_dir: Path,
    parent_path: str,
    name: str,
    role: str,
    description: str,
    system_prompt: str,
    model: str = "zen",
    max_iterations: int = 60,
    enabled_toolsets: Optional[list[str]] = None,
    team: Optional[str] = None,
) -> dict:
    agents_dir = Path(agents_dir).resolve()
    if team:
        agent_dir = agents_dir / parent_path / team / name
    else:
        agent_dir = agents_dir / parent_path / name

    if agent_dir.exists():
        return {
            "success": False,
            "error": f"Agent already exists at {agent_dir.relative_to(agents_dir)}",
        }

    agent_dir.mkdir(parents=True, exist_ok=True)

    toolsets = enabled_toolsets or []

    content = _SPAWN_TEMPLATE.format(
        name=name,
        description=description,
        role=role,
        model=model,
        max_iterations=max_iterations,
        toolsets_yaml=_toolsets_yaml(toolsets),
        system_prompt=system_prompt.strip(),
    )

    md_path = agent_dir / "AGENT.md"
    md_path.write_text(content, encoding="utf-8")

    return {
        "success": True,
        "agent_path": str(agent_dir.relative_to(agents_dir)),
        "name": name,
        "role": role,
    }


def remove_agent(
    agents_dir: Path,
    agent_path: str,
    archive: bool = True,
) -> dict:
    agents_dir = Path(agents_dir).resolve()
    target = agents_dir / agent_path

    if not target.exists():
        return {"success": False, "error": f"Agent not found at {agent_path}"}

    if archive:
        archive_dir = agents_dir / ".archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        dest = archive_dir / target.name
        # Avoid name collision in archive
        n = 2
        while dest.exists():
            dest = archive_dir / f"{target.name}-{n}"
            n += 1
        target.rename(dest)
    else:
        import shutil
        shutil.rmtree(target)

    return {"success": True, "action": "archived" if archive else "deleted"}


def agent_tool_schema() -> dict:
    return {
        "name": "hive_spawn_agent",
        "description": (
            "Create a new agent in the hive hierarchy by writing an AGENT.md file. "
            "Use this when you need a specialist for a domain you don't have."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "parent_path": {
                    "type": "string",
                    "description": "Relative path from agents/, e.g. 'queen-bee'",
                },
                "name": {
                    "type": "string",
                    "description": "Agent name (kebab-case, used as folder name)",
                },
                "role": {
                    "type": "string",
                    "enum": ["orchestrator", "soldier"],
                    "description": "orchestrator=general, soldier=worker",
                },
                "description": {
                    "type": "string",
                    "description": "One-line description of what this agent does",
                },
                "model": {
                    "type": "string",
                    "default": "zen",
                    "description": "Model to use (default: zen)",
                },
                "max_iterations": {
                    "type": "integer",
                    "default": 60,
                    "description": "Tool call budget for the agent",
                },
                "enabled_toolsets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Toolsets this agent can use",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "The agent's instructions — what it does, who it reports to",
                },
                "team": {
                    "type": "string",
                    "description": "Optional team folder to place the agent under",
                },
            },
            "required": ["parent_path", "name", "role", "description", "system_prompt"],
        },
    }


def remove_tool_schema() -> dict:
    return {
        "name": "hive_remove_agent",
        "description": "Remove an agent from the hive (archives to .archive/ by default)",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_path": {
                    "type": "string",
                    "description": "Path relative to agents/, e.g. 'queen-bee/general-backend'",
                },
                "permanent": {
                    "type": "boolean",
                    "default": False,
                    "description": "Delete permanently instead of archiving",
                },
            },
            "required": ["agent_path"],
        },
    }
