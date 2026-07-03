from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from textwrap import wrap

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

    margin = 56.0
    layer_gap = 92.0
    item_gap = 30.0
    layer_ids = sorted(by_layer)
    node_sizes: dict[str, tuple[float, float]] = {}
    for node in diagram.nodes.values():
        node_sizes[node.id] = _node_size(node.label, node.shape)

    layer_main_size: dict[int, float] = {}
    for layer in layer_ids:
        if horizontal:
            layer_main_size[layer] = max((node_sizes[node.id][0] for node in by_layer[layer]), default=112.0)
        else:
            layer_main_size[layer] = max((node_sizes[node.id][1] for node in by_layer[layer]), default=50.0)

    layer_offsets: dict[int, float] = {}
    cursor_main = margin
    for layer in layer_ids:
        layer_offsets[layer] = cursor_main
        cursor_main += layer_main_size[layer] + layer_gap

    node_boxes: dict[str, Box] = {}
    for layer in layer_ids:
        cursor_cross = margin
        nodes = by_layer[layer]
        for node in nodes:
            width, height = node_sizes[node.id]
            if horizontal:
                x = layer_offsets[layer] + (layer_main_size[layer] - width) / 2
                y = cursor_cross
                cursor_cross += height + item_gap
            else:
                x = cursor_cross
                y = layer_offsets[layer] + (layer_main_size[layer] - height) / 2
                cursor_cross += width + item_gap
            node_boxes[node.id] = Box(x=x, y=y, width=width, height=height)

    width = max((box.x + box.width for box in node_boxes.values()), default=240.0) + margin
    height = max((box.y + box.height for box in node_boxes.values()), default=160.0) + margin
    group_boxes = _group_boxes(diagram, node_boxes)
    if group_boxes:
        width = max(width, max(box.x + box.width for box in group_boxes.values()) + 24)
        height = max(height, max(box.y + box.height for box in group_boxes.values()) + 24)
    return Layout(node_boxes=node_boxes, group_boxes=group_boxes, width=width, height=height, direction=direction)


def _assign_layers(diagram: Diagram) -> dict[str, int]:
    """Assign coarse ranks without letting cycles inflate the canvas.

    The first implementation used repeated relaxation. On a graph with a small
    cycle, for example A -> B -> C -> A, every pass pushed the cycle farther and
    farther away. The result was technically valid SVG, but the GUI had to fit a
    6000+ px canvas into the preview and all useful content became microscopic.

    This version performs a cycle-safe breadth-first rank assignment. It still
    gives ordinary chains readable layers, but already processed nodes are not
    moved again by back-edges.
    """
    node_ids = list(diagram.nodes.keys())
    if not node_ids:
        return {}

    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_ids}
    node_id_set = set(node_ids)
    for edge in diagram.edges:
        if not edge.directed:
            continue
        if edge.source not in node_id_set or edge.target not in node_id_set:
            continue
        outgoing[edge.source].append(edge.target)
        indegree[edge.target] += 1

    layers: dict[str, int] = {}
    processed: set[str] = set()
    roots = [node_id for node_id in node_ids if indegree.get(node_id, 0) == 0]
    pending_roots = deque(roots or [node_ids[0]])

    def visit_from(start: str) -> None:
        queue: deque[str] = deque([start])
        layers.setdefault(start, 0)
        while queue:
            current = queue.popleft()
            if current in processed:
                continue
            processed.add(current)
            base = layers.get(current, 0)
            for target in outgoing.get(current, []):
                wanted = base + 1
                if target not in layers:
                    layers[target] = wanted
                    queue.append(target)
                elif target not in processed and wanted > layers[target]:
                    layers[target] = wanted
                    queue.append(target)

    while pending_roots:
        root = pending_roots.popleft()
        if root not in processed:
            visit_from(root)

    for node_id in node_ids:
        if node_id not in processed:
            layers.setdefault(node_id, 0)
            visit_from(node_id)

    return layers


def wrapped_label_lines(label: str, *, max_chars: int = 28) -> list[str]:
    lines: list[str] = []
    for raw_line in label.splitlines() or [label]:
        raw_line = raw_line.strip()
        if not raw_line:
            lines.append("")
            continue
        wrapped = wrap(raw_line, width=max_chars, break_long_words=False, replace_whitespace=False)
        lines.extend(wrapped or [raw_line])
    return lines or [label]


def _node_size(label: str, shape: str) -> tuple[float, float]:
    lines = wrapped_label_lines(label)
    longest = max((len(line) for line in lines), default=1)
    width = max(116.0, min(270.0, 42.0 + longest * 7.4))
    height = max(50.0, 30.0 + len(lines) * 18.0)
    if shape == "circle":
        size = max(width, height, 74.0)
        return size, size
    if shape == "diamond":
        return max(width + 28.0, 124.0), max(height + 28.0, 82.0)
    if shape in {"parallelogram", "parallelogram_alt", "hex"}:
        return width + 20.0, height
    return width, height


def _group_boxes(diagram: Diagram, node_boxes: dict[str, Box]) -> dict[str, Box]:
    group_boxes: dict[str, Box] = {}
    for group_id in diagram.groups:
        boxes = [box for node_id, box in node_boxes.items() if diagram.nodes[node_id].group == group_id]
        if not boxes:
            continue
        padding_x = 30.0
        padding_y = 44.0
        min_x = min(box.x for box in boxes) - padding_x
        min_y = min(box.y for box in boxes) - padding_y
        max_x = max(box.x + box.width for box in boxes) + padding_x
        max_y = max(box.y + box.height for box in boxes) + padding_y
        group_boxes[group_id] = Box(min_x, min_y, max_x - min_x, max_y - min_y)
    return group_boxes
