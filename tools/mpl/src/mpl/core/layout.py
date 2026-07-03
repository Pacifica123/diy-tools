from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict, deque

from .model import Diagram, Node


@dataclass(slots=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def cx(self) -> float:
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2


@dataclass(slots=True)
class Layout:
    node_boxes: dict[str, Box]
    group_boxes: dict[str, Box]
    width: float
    height: float
    direction: str


def build_layout(diagram: Diagram) -> Layout:
    direction = diagram.direction.upper()
    horizontal = direction in {"LR", "RL"}
    layers = _assign_layers(diagram)
    if direction in {"RL", "BT"} and layers:
        max_layer = max(layers.values())
        layers = {node_id: max_layer - layer for node_id, layer in layers.items()}

    by_layer: dict[int, list[Node]] = defaultdict(list)
    for node in diagram.nodes.values():
        by_layer[layers.get(node.id, 0)].append(node)
    for nodes in by_layer.values():
        nodes.sort(key=lambda item: item.id)

    margin = 48.0
    layer_gap = 130.0
    item_gap = 38.0
    node_boxes: dict[str, Box] = {}

    for layer in sorted(by_layer):
        cursor = margin
        for node in by_layer[layer]:
            width, height = _node_size(node.label, node.shape)
            if horizontal:
                x = margin + layer * layer_gap
                y = cursor
                cursor += height + item_gap
            else:
                x = cursor
                y = margin + layer * layer_gap
                cursor += width + item_gap
            node_boxes[node.id] = Box(x=x, y=y, width=width, height=height)

    width = max((box.x + box.width for box in node_boxes.values()), default=240.0) + margin
    height = max((box.y + box.height for box in node_boxes.values()), default=160.0) + margin
    group_boxes = _group_boxes(diagram, node_boxes)
    if group_boxes:
        width = max(width, max(box.x + box.width for box in group_boxes.values()) + 24)
        height = max(height, max(box.y + box.height for box in group_boxes.values()) + 24)
    return Layout(node_boxes=node_boxes, group_boxes=group_boxes, width=width, height=height, direction=direction)


def _assign_layers(diagram: Diagram) -> dict[str, int]:
    node_ids = list(diagram.nodes.keys())
    layers = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in diagram.edges:
        outgoing[edge.source].append(edge.target)
        if edge.directed:
            indegree[edge.target] = indegree.get(edge.target, 0) + 1
            indegree.setdefault(edge.source, 0)

    queue = deque([node_id for node_id, degree in indegree.items() if degree == 0])
    seen: set[str] = set()
    while queue:
        current = queue.popleft()
        seen.add(current)
        for target in outgoing.get(current, []):
            layers[target] = max(layers.get(target, 0), layers.get(current, 0) + 1)
            indegree[target] = indegree.get(target, 0) - 1
            if indegree[target] <= 0 and target not in seen:
                queue.append(target)

    for _ in range(max(1, len(diagram.edges))):
        changed = False
        for edge in diagram.edges:
            wanted = layers.get(edge.source, 0) + (1 if edge.directed else 0)
            if wanted > layers.get(edge.target, 0):
                layers[edge.target] = min(wanted, len(node_ids))
                changed = True
        if not changed:
            break
    return layers


def _node_size(label: str, shape: str) -> tuple[float, float]:
    lines = [part for part in label.splitlines() if part] or [label]
    longest = max((len(line) for line in lines), default=1)
    width = max(112.0, min(260.0, 54.0 + longest * 7.2))
    height = max(50.0, 34.0 + len(lines) * 18.0)
    if shape == "circle":
        size = max(width, height, 72.0)
        return size, size
    if shape == "diamond":
        return max(width + 20.0, 120.0), max(height + 24.0, 78.0)
    return width, height


def _group_boxes(diagram: Diagram, node_boxes: dict[str, Box]) -> dict[str, Box]:
    group_boxes: dict[str, Box] = {}
    for group_id in diagram.groups:
        boxes = [box for node_id, box in node_boxes.items() if diagram.nodes[node_id].group == group_id]
        if not boxes:
            continue
        padding_x = 28.0
        padding_y = 38.0
        min_x = min(box.x for box in boxes) - padding_x
        min_y = min(box.y for box in boxes) - padding_y
        max_x = max(box.x + box.width for box in boxes) + padding_x
        max_y = max(box.y + box.height for box in boxes) + padding_y
        group_boxes[group_id] = Box(min_x, min_y, max_x - min_x, max_y - min_y)
    return group_boxes
