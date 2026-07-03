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


@dataclass(slots=True)
class _LayoutConfig:
    margin: float = 64.0
    layer_gap: float = 116.0
    item_gap: float = 34.0
    group_padding_x: float = 34.0
    group_padding_y: float = 48.0


def build_layout(diagram: Diagram) -> Layout:
    direction = diagram.direction.upper()
    horizontal = direction in {"LR", "RL"}
    config = _LayoutConfig()

    layers = _assign_layers(diagram)
    if direction in {"RL", "BT"} and layers:
        max_layer = max(layers.values())
        layers = {node_id: max_layer - layer for node_id, layer in layers.items()}

    layer_order = _ordered_layers(diagram, layers, horizontal=horizontal)
    node_sizes = {node.id: _node_size(node.label, node.shape) for node in diagram.nodes.values()}

    layer_main_size: dict[int, float] = {}
    for layer, node_ids in layer_order.items():
        if horizontal:
            layer_main_size[layer] = max((node_sizes[node_id][0] for node_id in node_ids), default=112.0)
        else:
            layer_main_size[layer] = max((node_sizes[node_id][1] for node_id in node_ids), default=50.0)

    layer_offsets: dict[int, float] = {}
    cursor_main = config.margin
    for layer in sorted(layer_order):
        layer_offsets[layer] = cursor_main
        cursor_main += layer_main_size[layer] + config.layer_gap

    node_boxes: dict[str, Box] = {}
    for layer in sorted(layer_order):
        cursor_cross = config.margin
        for node_id in layer_order[layer]:
            width, height = node_sizes[node_id]
            if horizontal:
                x = layer_offsets[layer] + (layer_main_size[layer] - width) / 2
                y = cursor_cross
                cursor_cross += height + config.item_gap
            else:
                x = cursor_cross
                y = layer_offsets[layer] + (layer_main_size[layer] - height) / 2
                cursor_cross += width + config.item_gap
            node_boxes[node_id] = Box(x=x, y=y, width=width, height=height)

    group_boxes = _group_boxes(diagram, node_boxes, config)
    width = max((box.x + box.width for box in node_boxes.values()), default=260.0) + config.margin
    height = max((box.y + box.height for box in node_boxes.values()), default=180.0) + config.margin
    if group_boxes:
        width = max(width, max(box.x + box.width for box in group_boxes.values()) + 28)
        height = max(height, max(box.y + box.height for box in group_boxes.values()) + 28)
    return Layout(node_boxes=node_boxes, group_boxes=group_boxes, width=width, height=height, direction=direction)


def _assign_layers(diagram: Diagram) -> dict[str, int]:
    """Assign coarse ranks without letting cycles inflate the canvas.

    The algorithm is intentionally simple: breadth-first ranks from roots,
    then one local correction pass for forward edges. Back-edges and cycles are
    allowed, but they no longer keep pushing nodes farther away forever.
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

    roots = [node_id for node_id in node_ids if indegree.get(node_id, 0) == 0] or [node_ids[0]]
    layers: dict[str, int] = {}
    seen: set[str] = set()

    for root in roots:
        if root in seen:
            continue
        layers.setdefault(root, 0)
        queue: deque[str] = deque([root])
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            base = layers.get(current, 0)
            for target in outgoing.get(current, []):
                if target not in layers:
                    layers[target] = base + 1
                elif target not in seen:
                    layers[target] = max(layers[target], base + 1)
                if target not in seen:
                    queue.append(target)

    for node_id in node_ids:
        if node_id not in layers:
            layers[node_id] = 0

    # Small local correction for ordinary forward chains. It is bounded on
    # purpose: diagrams should stay compact even with cycles.
    max_layer = max(0, len(node_ids) - 1)
    for edge in diagram.edges:
        if edge.source in layers and edge.target in layers and edge.directed:
            if layers[edge.target] <= layers[edge.source] and edge.target not in roots:
                layers[edge.target] = min(max_layer, layers[edge.source] + 1)

    return layers


def _ordered_layers(diagram: Diagram, layers: dict[str, int], *, horizontal: bool) -> dict[int, list[str]]:
    by_layer: dict[int, list[str]] = defaultdict(list)
    for node_id in diagram.nodes:
        by_layer[layers.get(node_id, 0)].append(node_id)

    if not by_layer:
        return {}

    insertion_order = {node_id: index for index, node_id in enumerate(diagram.nodes)}
    group_order = {group_id: index for index, group_id in enumerate(diagram.groups)}

    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    node_ids = set(diagram.nodes)
    for edge in diagram.edges:
        if edge.source in node_ids and edge.target in node_ids:
            outgoing[edge.source].append(edge.target)
            incoming[edge.target].append(edge.source)
            if edge.bidirectional:
                outgoing[edge.target].append(edge.source)
                incoming[edge.source].append(edge.target)

    positions = _positions(by_layer)
    layers_sorted = sorted(by_layer)

    def group_rank(node_id: str) -> int:
        group_id = diagram.nodes[node_id].group
        if group_id is None:
            return 10_000 + insertion_order[node_id]
        return group_order.get(group_id, 9_000)

    def barycenter(node_id: str, refs: list[str]) -> float | None:
        values = [positions[item] for item in refs if item in positions]
        if not values:
            return None
        return sum(values) / len(values)

    def sort_layer(layer: int, neighbor_map: dict[str, list[str]]) -> None:
        current = list(by_layer[layer])
        current_pos = {node_id: index for index, node_id in enumerate(current)}

        def key(node_id: str) -> tuple[float, int, int]:
            bary = barycenter(node_id, neighbor_map.get(node_id, []))
            if bary is None:
                bary = current_pos[node_id]
            return (bary, group_rank(node_id), insertion_order[node_id])

        by_layer[layer] = sorted(current, key=key)

    # A few deterministic barycentric passes. This is not Graphviz, but it
    # removes many avoidable crossings in common flowcharts.
    for _ in range(4):
        positions = _positions(by_layer)
        for layer in layers_sorted[1:]:
            sort_layer(layer, incoming)
        positions = _positions(by_layer)
        for layer in reversed(layers_sorted[:-1]):
            sort_layer(layer, outgoing)

    # Keep subgraph members visually contiguous after the crossing-reduction
    # pass. This is a soft regrouping, not a full compound-graph layout.
    for layer, node_ids_in_layer in list(by_layer.items()):
        by_layer[layer] = sorted(
            node_ids_in_layer,
            key=lambda node_id: (_group_bucket(diagram.nodes[node_id], group_order), node_ids_in_layer.index(node_id)),
        )

    return dict(sorted(by_layer.items()))


def _group_bucket(node: Node, group_order: dict[str, int]) -> tuple[int, int]:
    if node.group is None:
        return (0, 10_000)
    return (1, group_order.get(node.group, 9_000))


def _positions(by_layer: dict[int, list[str]]) -> dict[str, float]:
    positions: dict[str, float] = {}
    for node_ids in by_layer.values():
        for index, node_id in enumerate(node_ids):
            positions[node_id] = float(index)
    return positions


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
    width = max(118.0, min(286.0, 44.0 + longest * 7.8))
    height = max(52.0, 32.0 + len(lines) * 18.0)
    if shape == "circle":
        size = max(width, height, 76.0)
        return size, size
    if shape == "diamond":
        return max(width + 36.0, 132.0), max(height + 34.0, 86.0)
    if shape in {"parallelogram", "parallelogram_alt", "hex"}:
        return width + 22.0, height
    return width, height


def _group_boxes(diagram: Diagram, node_boxes: dict[str, Box], config: _LayoutConfig) -> dict[str, Box]:
    group_boxes: dict[str, Box] = {}
    # Children first, then parent groups may include nested group boxes.
    group_ids = list(diagram.groups)
    for group_id in reversed(group_ids):
        member_boxes = [box for node_id, box in node_boxes.items() if diagram.nodes[node_id].group == group_id]
        child_boxes = [box for child_id, box in group_boxes.items() if diagram.groups[child_id].parent == group_id]
        boxes = member_boxes + child_boxes
        if not boxes:
            continue
        min_x = min(box.x for box in boxes) - config.group_padding_x
        min_y = min(box.y for box in boxes) - config.group_padding_y
        max_x = max(box.x + box.width for box in boxes) + config.group_padding_x
        max_y = max(box.y + box.height for box in boxes) + config.group_padding_y
        group_boxes[group_id] = Box(min_x, min_y, max_x - min_x, max_y - min_y)
    # Preserve declaration order for rendering.
    return {group_id: group_boxes[group_id] for group_id in group_ids if group_id in group_boxes}
