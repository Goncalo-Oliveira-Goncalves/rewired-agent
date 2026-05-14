import json
from pathlib import Path

from tools.registry import registry
from tools.hive_common import _AGENTS_DIR, _hive_available

_SPAWN_TEMPLATE = """\
---
name: {name}
version: "1.0"
description: {description}
role: {role}
model: {model}
max_iterations: {max_iterations}
enabled_toolsets:
{toolsets_yaml}
---
{system_prompt}
"""


def _toolsets_yaml(toolsets: list[str]) -> str:
    if not toolsets:
        return "  []"
    return "\n".join(f"  - {t}" for t in toolsets)


def handle_spawn(
    parent_path: str,
    name: str,
    role: str,
    description: str,
    system_prompt: str,
    model: str = "zen",
    max_iterations: int = 60,
    enabled_toolsets: list[str] = None,
    team: str = None,
    **kwargs,
) -> str:
    try:
        agents_dir = _AGENTS_DIR
        if team:
            agent_dir = agents_dir / parent_path / team / name
        else:
            agent_dir = agents_dir / parent_path / name

        if agent_dir.exists():
            return json.dumps({
                "success": False,
                "error": f"Agent already exists at {agent_dir.relative_to(agents_dir)}",
            })

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

        (agent_dir / "AGENT.md").write_text(content, encoding="utf-8")

        return json.dumps({
            "success": True,
            "agent_path": str(agent_dir.relative_to(agents_dir)),
            "name": name,
            "role": role,
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def handle_remove(agent_path: str, permanent: bool = False, **kwargs) -> str:
    try:
        target = _AGENTS_DIR / agent_path
        if not target.exists():
            return json.dumps({"success": False, "error": f"Not found: {agent_path}"})

        if permanent:
            import shutil
            shutil.rmtree(target)
            action = "deleted"
        else:
            archive = _AGENTS_DIR / ".archive"
            archive.mkdir(parents=True, exist_ok=True)
            dest = archive / target.name
            n = 2
            while dest.exists():
                dest = archive / f"{target.name}-{n}"
                n += 1
            target.rename(dest)
            action = "archived"

        return json.dumps({"success": True, "action": action, "agent_path": agent_path})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


_SPAWN_SCHEMA = {
    "name": "hive_spawn_agent",
    "description": "Create a new agent in the hive hierarchy. Use when you need a specialist for a domain you don't have.",
    "parameters": {
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
            },
            "enabled_toolsets": {
                "type": "array",
                "items": {"type": "string"},
            },
            "system_prompt": {
                "type": "string",
                "description": "The agent's instructions",
            },
            "team": {
                "type": "string",
                "description": "Optional team folder to place the agent under",
            },
        },
        "required": ["parent_path", "name", "role", "description", "system_prompt"],
    },
}

_REMOVE_SCHEMA = {
    "name": "hive_remove_agent",
    "description": "Remove an agent from the hive (archives to .archive/ by default)",
    "parameters": {
        "type": "object",
        "properties": {
            "agent_path": {
                "type": "string",
                "description": "Path relative to agents/, e.g. 'queen-bee/general-backend'",
            },
            "permanent": {
                "type": "boolean",
                "default": False,
            },
        },
        "required": ["agent_path"],
    },
}

registry.register(
    name="hive_spawn_agent",
    toolset="hive",
    schema=_SPAWN_SCHEMA,
    handler=lambda args, h=handle_spawn: h(**args),
    check_fn=_hive_available,
    emoji="🐝",
)
registry.register(
    name="hive_remove_agent",
    toolset="hive",
    schema=_REMOVE_SCHEMA,
    handler=lambda args, h=handle_remove: h(**args),
    check_fn=_hive_available,
    emoji="🐝",
)
