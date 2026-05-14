from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class AgentNode:
    name: str
    path: Path
    agent_md: Dict[str, Any]
    level: int
    is_team: bool = False
    parent: Optional["AgentNode"] = field(default=None, repr=False)
    children: List["AgentNode"] = field(default_factory=list)

    @property
    def role(self) -> str:
        return self.agent_md.get("role", "soldier")

    @property
    def model(self) -> str:
        return self.agent_md.get("model", "claude-sonnet-4-6")

    @property
    def description(self) -> str:
        return self.agent_md.get("description", "")

    @property
    def system_prompt(self) -> str:
        return self.agent_md.get("_system_prompt", "")

    @property
    def tools(self) -> List[str]:
        return self.agent_md.get("tools", [])

    def add_child(self, child: "AgentNode") -> None:
        child.parent = self
        self.children.append(child)

    def agents_only(self) -> List["AgentNode"]:
        """Return all non-team descendants (recursive)."""
        result = []
        for child in self.children:
            if not child.is_team:
                result.append(child)
            result.extend(child.agents_only())
        return result

    def __repr__(self) -> str:
        tag = "TEAM" if self.is_team else self.role.upper()
        return f"AgentNode({self.name!r}, level={self.level}, [{tag}])"


@dataclass
class HiveTree:
    root: AgentNode
    _nodes_by_name: Dict[str, AgentNode] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._index(self.root)

    def _index(self, node: AgentNode) -> None:
        if not node.is_team:
            self._nodes_by_name[node.name] = node
        for child in node.children:
            self._index(child)

    @property
    def queen(self) -> Optional[AgentNode]:
        for child in self.root.children:
            if not child.is_team and (
                child.name == "queen-bee" or child.role == "queen"
            ):
                return child
        return None

    @property
    def all_agents(self) -> List[AgentNode]:
        """All non-team nodes in the tree (excluding synthetic root)."""
        return self.root.agents_only()

    def get_by_name(self, name: str) -> Optional[AgentNode]:
        return self._nodes_by_name.get(name)

    def get_level(self, level: int) -> List[AgentNode]:
        return [n for n in self.all_agents if n.level == level]

    def is_empty(self) -> bool:
        """True if no real agents exist below root (queen not yet created)."""
        return len(self.all_agents) == 0

    def pretty_print(self, node: AgentNode | None = None, indent: int = 0) -> str:
        node = node or self.root
        tag = "(team)" if node.is_team else f"[{node.role}]"
        lines = [f"{'  ' * indent}{node.name} {tag}"]
        for child in node.children:
            lines.append(self.pretty_print(child, indent + 1))
        return "\n".join(lines)
