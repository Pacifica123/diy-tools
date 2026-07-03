from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from textwrap import wrap

from .model import Diagram, Edge, Node


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
    layer_gap: float = 112.0
    item_gap: float = 34.0
    wrap_gap_main: float = 34.0
    max_cross_span: float = 1120.0
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

    layer_order = _ordered_layers(diagram, layers)
    node_sizes = {node.id: _node_size(node.label, node.shape) for node in diagram.nodes.values()}
    packed, layer_main_size = _pack_layers(layer_order, node_sizes, horizontal=horizontal, config=config)

    layer_offsets: dict[int, float] = {}
    cursor_main = config.margin
    for layer in sorted(layer_order):
        layer_offsets[layer] = cursor_main
        cursor_main += layer_main_size.get(layer, 52.0) + config.layer_gap

    node_boxes: dict[str, Box] = {}
    for node_id, packed_item in packed.items():
        layer = packed_item.layer
        width, height = node_sizes[node_id]
        if horizontal:
            x = layer_offsets[layer] + packed_item.main
            y = packed_item.cross
        else:
            x = packed_item.cross
            y = layer_offsets[layer] + packed_item.main
        node_boxes[node_id] = Box(x=x, y=y, width=width, height=height)

    group_boxes = _group_boxes(diagram, node_boxes, config)
    if len(group_boxes) > 1:
        _separate_top_level_groups(diagram, node_boxes, group_boxes, direction, config)
        group_boxes = _group_boxes(diagram, node_boxes, config)

    width = max((box.x + box.width for box in node_boxes.values()), default=260.0) + config.margin
    height = max((box.y + box.height for box in node_boxes.values()), default=180.0) + config.margin
    if group_boxes:
        width = max(width, max(box.x + box.width for box in group_boxes.values()) + 28)
        height = max(height, max(box.y + box.height for box in group_boxes.values()) + 28)
    return Layout(node_boxes=node_boxes, group_boxes=group_boxes, width=width, height=height, direction=direction)


@dataclass(slots=True)
class _PackedItem:
    layer: int
    cross: float
    main: float


def _pack_layers(
    layer_order: dict[int, list[str]],
    node_sizes: dict[str, tuple[float, float]],
    *,
    horizontal: bool,
    config: _LayoutConfig,
) -> tuple[dict[str, _PackedItem], dict[int, float]]:
    packed: dict[str, _PackedItem] = {}
    layer_main_size: dict[int, float] = {}
    cross_limit = config.margin + config.max_cross_span

    for layer, node_ids in layer_order.items():
        cross_cursor = config.margin
        main_cursor = 0.0
        row_or_column_main = 0.0
        used_any = False

        for node_id in node_ids:
            width, height = node_sizes[node_id]
            item_cross = height if horizontal else width
            item_main = width if horizontal else height

            if used_any and cross_cursor + item_cross > cross_limit:
                main_cursor += row_or_column_main + config.wrap_gap_main
                cross_cursor = config.margin
                row_or_column_main = 0.0

            packed[node_id] = _PackedItem(layer=layer, cross=cross_cursor, main=main_cursor)
            cross_cursor += item_cross + config.item_gap
            row_or_column_main = max(row_or_column_main, item_main)
            used_any = True

        layer_main_size[layer] = max(52.0, main_cursor + row_or_column_main)
    return packed, layer_main_size


def _assign_layers(diagram: Diagram) -> dict[str, int]:
    """Assign coarse ranks without letting cycles or subgraph crossings inflate the canvas.

    External edges that enter or leave a subgraph are still rendered, but they do
    not force internal group nodes to be scattered across the whole document.
    That keeps subgraphs usable as visual clusters instead of huge translucent
    blankets over unrelated nodes.
    """
    node_ids = list(diagram.nodes.keys())
    if not node_ids:
        return {}

    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_ids}
    node_id_set = set(node_ids)

    for edge in diagram.edges:
        if not _edge_affects_rank(edge, diagram, node_id_set):
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

    max_layer = max(0, len(node_ids) - 1)
    for edge in diagram.edges:
        if not _edge_affects_rank(edge, diagram, node_id_set):
            continue
        if layers[edge.target] <= layers[edge.source] and edge.target not in roots:
            layers[edge.target] = min(max_layer, layers[edge.source] + 1)

    return layers


def _edge_affects_rank(edge: Edge, diagram: Diagram, node_id_set: set[str]) -> bool:
    if not edge.directed:
        return False
    if edge.source not in node_id_set or edge.target not in node_id_set:
        return False
    source_group = diagram.nodes[edge.source].group
    target_group = diagram.nodes[edge.target].group
    if source_group != target_group and (source_group is not None or target_group is not None):
        return False
    return True


def _ordered_layers(diagram: Diagram, layers: dict[str, int]) -> dict[int, list[str]]:
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

    def group_rank(node_id: str) -> tuple[int, int]:
        group_id = diagram.nodes[node_id].group
        if group_id is None:
            return (0, insertion_order[node_id])
        return (1 + group_order.get(group_id, 9_000), insertion_order[node_id])

    def barycenter(node_id: str, refs: list[str]) -> float | None:
        values = [positions[item] for item in refs if item in positions]
        if not values:
            return None
        return sum(values) / len(values)

    def sort_layer(layer: int, neighbor_map: dict[str, list[str]]) -> None:
        current = list(by_layer[layer])
        current_pos = {node_id: index for index, node_id in enumerate(current)}

        def key(node_id: str) -> tuple[float, tuple[int, int], int]:
            bary = barycenter(node_id, neighbor_map.get(node_id, []))
            if bary is None:
                bary = current_pos[node_id]
            return (bary, group_rank(node_id), insertion_order[node_id])

        by_layer[layer] = sorted(current, key=key)

    for _ in range(4):
        positions = _positions(by_layer)
        for layer in layers_sorted[1:]:
            sort_layer(layer, incoming)
        positions = _positions(by_layer)
        for layer in reversed(layers_sorted[:-1]):
            sort_layer(layer, outgoing)

    for layer, node_ids_in_layer in list(by_layer.items()):
        by_layer[layer] = sorted(
            node_ids_in_layer,
            key=lambda node_id: (_group_bucket(diagram.nodes[node_id], group_order), node_ids_in_layer.index(node_id)),
        )

    return dict(sorted(by_layer.items()))


def _group_bucket(node: Node, group_order: dict[str, int]) -> tuple[int, int]:
    if node.group is None:
        return (0, 0)
    return (1 + group_order.get(node.group, 9_000), 0)


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
    return {group_id: group_boxes[group_id] for group_id in group_ids if group_id in group_boxes}


def _separate_top_level_groups(
    diagram: Diagram,
    node_boxes: dict[str, Box],
    group_boxes: dict[str, Box],
    direction: str,
    config: _LayoutConfig,
) -> None:
    top_groups = [group_id for group_id, group in diagram.groups.items() if group.parent is None and group_id in group_boxes]
    if len(top_groups) < 2:
        return

    horizontal = direction.upper() in {"LR", "RL"}
    placed: list[Box] = []
    for group_id in top_groups:
        box = group_boxes[group_id]
        shift_x = 0.0
        shift_y = 0.0

        colliding = [other for other in placed if _boxes_overlap(box, other, padding=18.0)]
        if colliding:
            if horizontal:
                shift_x = max(other.x + other.width for other in colliding) + config.layer_gap - box.x
            else:
                shift_y = max(other.y + other.height for other in colliding) + config.layer_gap - box.y
            _shift_group_tree(diagram, node_boxes, group_id, shift_x, shift_y)
            box = Box(box.x + shift_x, box.y + shift_y, box.width, box.height)

        placed.append(box)


def _boxes_overlap(left: Box, right: Box, *, padding: float = 0.0) -> bool:
    return not (
        left.x + left.width + padding <= right.x
        or right.x + right.width + padding <= left.x
        or left.y + left.height + padding <= right.y
        or right.y + right.height + padding <= left.y
    )


def _shift_group_tree(diagram: Diagram, node_boxes: dict[str, Box], group_id: str, dx: float, dy: float) -> None:
    group_ids = {group_id}
    changed = True
    while changed:
        changed = False
        for child_id, group in diagram.groups.items():
            if group.parent in group_ids and child_id not in group_ids:
                group_ids.add(child_id)
                changed = True

    for node_id, node in diagram.nodes.items():
        if node.group not in group_ids:
            continue
        box = node_boxes[node_id]
        node_boxes[node_id] = Box(box.x + dx, box.y + dy, box.width, box.height)
