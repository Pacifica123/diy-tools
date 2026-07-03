from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class Node:
    id: str
    label: str
    shape: str = "rect"
    group: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    label: str = ""
    directed: bool = True
    bidirectional: bool = False
    style: str = "normal"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Group:
    id: str
    label: str
    parent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Diagram:
    kind: str = "flowchart"
    direction: str = "TD"
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    groups: dict[str, Group] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add_node(self, node: Node) -> Node:
        old = self.nodes.get(node.id)
        if old is None:
            self.nodes[node.id] = node
            return node
        if old.label == old.id and node.label != node.id:
            old.label = node.label
        if old.shape == "rect" and node.shape != "rect":
            old.shape = node.shape
        if old.group is None and node.group is not None:
            old.group = node.group
        return old

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "direction": self.direction,
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
            "groups": [group.to_dict() for group in self.groups.values()],
            "warnings": list(self.warnings),
        }
