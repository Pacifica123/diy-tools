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
    layer_gap: float = 100.0
    item_gap: float = 36.0
    wrap_gap_main: float = 44.0
    max_cross_span: float = 1000.0
    group_padding_x: float = 28.0
    group_padding_top: float = 52.0
    group_padding_bottom: float = 30.0


@dataclass(slots=True)
class _PackedItem:
    layer: int
    cross: float
    main: float


@dataclass(slots=True)
class _ItemEdge:
    source: str
    target: str
    directed: bool = True


def build_layout(diagram: Diagram) -> Layout:
    """Build a readable lightweight layout.

    v5 still mixed nodes from top-level subgraphs into the same global rank grid
    as ordinary nodes. Long internal chains inside a subgraph therefore stretched
    the group across unrelated parts of the document. v6 treats every top-level
    subgraph as a compact cluster item in the global layout and lays out its
    children inside that cluster independently.
    """
    direction = diagram.direction.upper()
    horizontal = direction in {"LR", "RL"}
    config = _LayoutConfig()

    top_groups = [group_id for group_id, group in diagram.groups.items() if group.parent is None]
    top_group_set = set(top_groups)
    group_members = _top_group_members(diagram, top_group_set)

    group_rel_boxes: dict[str, dict[str, Box]] = {}
    group_sizes: dict[str, tuple[float, float]] = {}
    for group_id in top_groups:
        rel_boxes, size = _layout_group_members(diagram, group_id, group_members[group_id], direction)
        group_rel_boxes[group_id] = rel_boxes
        group_sizes[group_id] = size

    item_sizes: dict[str, tuple[float, float]] = {}
    for node_id, node in diagram.nodes.items():
        if _owning_top_group(node, diagram, top_group_set) is None:
            item_sizes[node_id] = _node_size(node.label, node.shape)
    for group_id, size in group_sizes.items():
        item_sizes[group_id] = size

    if not item_sizes:
        return Layout(node_boxes={}, group_boxes={}, width=260.0, height=180.0, direction=direction)

    item_order = _global_item_order(diagram, item_sizes.keys(), top_group_set, group_members)
    top_edges = _global_item_edges(diagram, top_group_set)
    layers = _assign_item_layers(item_order, top_edges)
    if direction in {"RL", "BT"} and layers:
        max_layer = max(layers.values())
        layers = {item_id: max_layer - layer for item_id, layer in layers.items()}

    layer_order = _ordered_item_layers(item_order, layers, top_edges)
    packed, layer_main_size = _pack_layers(layer_order, item_sizes, horizontal=horizontal, config=config)

    layer_offsets: dict[int, float] = {}
    cursor_main = config.margin
    for layer in sorted(layer_order):
        layer_offsets[layer] = cursor_main
        cursor_main += layer_main_size.get(layer, 52.0) + config.layer_gap

    node_boxes: dict[str, Box] = {}
    group_boxes: dict[str, Box] = {}
    for item_id, packed_item in packed.items():
        layer = packed_item.layer
        width, height = item_sizes[item_id]
        if horizontal:
            item_box = Box(
                x=layer_offsets[layer] + packed_item.main,
                y=packed_item.cross,
                width=width,
                height=height,
            )
        else:
            item_box = Box(
                x=packed_item.cross,
                y=layer_offsets[layer] + packed_item.main,
                width=width,
                height=height,
            )

        if item_id in top_group_set:
            group_boxes[item_id] = item_box
            for node_id, rel_box in group_rel_boxes[item_id].items():
                node_boxes[node_id] = Box(
                    x=item_box.x + rel_box.x,
                    y=item_box.y + rel_box.y,
                    width=rel_box.width,
                    height=rel_box.height,
                )
        else:
            node_boxes[item_id] = item_box

    # Fallback for nested or otherwise unusual group membership not covered by
    # the top-level cluster pass. This keeps the renderer tolerant instead of
    # silently dropping nodes.
    for node_id, node in diagram.nodes.items():
        if node_id not in node_boxes:
            width, height = _node_size(node.label, node.shape)
            node_boxes[node_id] = Box(config.margin, config.margin, width, height)

    for group_id, group in diagram.groups.items():
        if group_id in group_boxes:
            continue
        boxes = [box for node_id, box in node_boxes.items() if diagram.nodes[node_id].group == group_id]
        if boxes:
            group_boxes[group_id] = _box_around(boxes, config)

    width = max((box.x + box.width for box in list(node_boxes.values()) + list(group_boxes.values())), default=260.0) + config.margin
    height = max((box.y + box.height for box in list(node_boxes.values()) + list(group_boxes.values())), default=180.0) + config.margin
    return Layout(node_boxes=node_boxes, group_boxes=group_boxes, width=width, height=height, direction=direction)


def _top_group_members(diagram: Diagram, top_group_set: set[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {group_id: [] for group_id in top_group_set}
    for node_id, node in diagram.nodes.items():
        owner = _owning_top_group(node, diagram, top_group_set)
        if owner is not None:
            result.setdefault(owner, []).append(node_id)
    return result


def _owning_top_group(node: Node, diagram: Diagram, top_group_set: set[str]) -> str | None:
    group_id = node.group
    seen: set[str] = set()
    while group_id is not None and group_id not in seen:
        if group_id in top_group_set:
            return group_id
        seen.add(group_id)
        group = diagram.groups.get(group_id)
        group_id = group.parent if group is not None else None
    return None


def _layout_group_members(diagram: Diagram, group_id: str, member_ids: list[str], direction: str) -> tuple[dict[str, Box], tuple[float, float]]:
    config = _LayoutConfig(margin=0.0, layer_gap=68.0, item_gap=28.0, wrap_gap_main=34.0, max_cross_span=760.0)
    horizontal = direction.upper() in {"LR", "RL"}
    node_sizes = {node_id: _node_size(diagram.nodes[node_id].label, diagram.nodes[node_id].shape) for node_id in member_ids}
    member_set = set(member_ids)
    internal_edges = [
        _ItemEdge(edge.source, edge.target, edge.directed)
        for edge in diagram.edges
        if edge.source in member_set and edge.target in member_set and edge.directed
    ]
    layers = _assign_item_layers(member_ids, internal_edges)
    if direction.upper() in {"RL", "BT"} and layers:
        max_layer = max(layers.values())
        layers = {item_id: max_layer - layer for item_id, layer in layers.items()}
    layer_order = _ordered_item_layers(member_ids, layers, internal_edges)
    packed, layer_main_size = _pack_layers(layer_order, node_sizes, horizontal=horizontal, config=config)

    layer_offsets: dict[int, float] = {}
    cursor_main = config.group_padding_top
    for layer in sorted(layer_order):
        layer_offsets[layer] = cursor_main
        cursor_main += layer_main_size.get(layer, 52.0) + config.layer_gap

    rel_boxes: dict[str, Box] = {}
    for node_id, packed_item in packed.items():
        width, height = node_sizes[node_id]
        if horizontal:
            x = config.group_padding_x + layer_offsets[packed_item.layer] + packed_item.main
            y = config.group_padding_top + packed_item.cross
        else:
            x = config.group_padding_x + packed_item.cross
            y = layer_offsets[packed_item.layer] + packed_item.main
        rel_boxes[node_id] = Box(x=x, y=y, width=width, height=height)

    if rel_boxes:
        width = max(box.x + box.width for box in rel_boxes.values()) + config.group_padding_x
        height = max(box.y + box.height for box in rel_boxes.values()) + config.group_padding_bottom
    else:
        width, height = 220.0, 120.0
    width = max(width, 220.0)
    height = max(height, 120.0)
    return rel_boxes, (width, height)


def _global_item_order(diagram: Diagram, item_ids, top_group_set: set[str], group_members: dict[str, list[str]]) -> list[str]:
    node_order = {node_id: index for index, node_id in enumerate(diagram.nodes)}
    fallback = len(node_order) + 100

    def order_key(item_id: str) -> int:
        if item_id in node_order:
            return node_order[item_id]
        members = group_members.get(item_id, [])
        if members:
            return min(node_order.get(member, fallback) for member in members)
        return fallback

    return sorted(item_ids, key=order_key)


def _global_item_edges(diagram: Diagram, top_group_set: set[str]) -> list[_ItemEdge]:
    result: list[_ItemEdge] = []
    seen: set[tuple[str, str, bool]] = set()

    def endpoint_item(endpoint: str) -> str | None:
        if endpoint in top_group_set:
            return endpoint
        node = diagram.nodes.get(endpoint)
        if node is None:
            return None
        return _owning_top_group(node, diagram, top_group_set) or endpoint

    for edge in diagram.edges:
        source = endpoint_item(edge.source)
        target = endpoint_item(edge.target)
        if source is None or target is None or source == target:
            continue
        key = (source, target, edge.directed)
        if key in seen:
            continue
        seen.add(key)
        result.append(_ItemEdge(source, target, edge.directed))
    return result


def _pack_layers(
    layer_order: dict[int, list[str]],
    item_sizes: dict[str, tuple[float, float]],
    *,
    horizontal: bool,
    config: _LayoutConfig,
) -> tuple[dict[str, _PackedItem], dict[int, float]]:
    packed: dict[str, _PackedItem] = {}
    layer_main_size: dict[int, float] = {}
    cross_limit = config.margin + config.max_cross_span

    for layer, item_ids in layer_order.items():
        cross_cursor = config.margin
        main_cursor = 0.0
        row_or_column_main = 0.0
        used_any = False

        for item_id in item_ids:
            width, height = item_sizes[item_id]
            item_cross = height if horizontal else width
            item_main = width if horizontal else height

            if used_any and cross_cursor + item_cross > cross_limit:
                main_cursor += row_or_column_main + config.wrap_gap_main
                cross_cursor = config.margin
                row_or_column_main = 0.0

            packed[item_id] = _PackedItem(layer=layer, cross=cross_cursor, main=main_cursor)
            cross_cursor += item_cross + config.item_gap
            row_or_column_main = max(row_or_column_main, item_main)
            used_any = True

        layer_main_size[layer] = max(52.0, main_cursor + row_or_column_main)
    return packed, layer_main_size


def _assign_item_layers(item_order: list[str], edges: list[_ItemEdge]) -> dict[str, int]:
    """Assign ranks with source order as the tie-breaker.

    Mermaid snippets written by hand often contain explanatory back-links such
    as "fix patch -> manifest". If those links affect ranking, older boxes jump
    across the page and long side wires appear. For the lightweight renderer we
    rank only forward-in-source edges and leave backward links to the router.
    Late disconnected components start after the already seen component instead
    of being pulled to the top.
    """
    if not item_order:
        return {}

    position = {item_id: index for index, item_id in enumerate(item_order)}
    item_set = set(item_order)
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming_forward: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if not edge.directed:
            continue
        if edge.source not in item_set or edge.target not in item_set:
            continue
        if position[edge.source] > position[edge.target]:
            continue
        outgoing[edge.source].append(edge.target)
        incoming_forward[edge.target].append(edge.source)

    layers: dict[str, int] = {}
    max_seen_layer = 0
    for item_id in item_order:
        if item_id not in layers:
            if not layers:
                layers[item_id] = 0
            elif not incoming_forward.get(item_id):
                layers[item_id] = max_seen_layer + 1
            else:
                layers[item_id] = 0
        max_seen_layer = max(max_seen_layer, layers[item_id])
        for target in outgoing.get(item_id, []):
            wanted = layers[item_id] + 1
            if wanted > layers.get(target, -1):
                layers[target] = wanted
                max_seen_layer = max(max_seen_layer, wanted)

    for _ in range(2):
        for edge in edges:
            if not edge.directed:
                continue
            if edge.source not in item_set or edge.target not in item_set:
                continue
            if position[edge.source] > position[edge.target]:
                continue
            layers[edge.target] = max(layers.get(edge.target, 0), layers.get(edge.source, 0) + 1)

    return layers


def _ordered_item_layers(item_order: list[str], layers: dict[str, int], edges: list[_ItemEdge]) -> dict[int, list[str]]:
    by_layer: dict[int, list[str]] = defaultdict(list)
    item_position = {item_id: index for index, item_id in enumerate(item_order)}
    for item_id in item_order:
        by_layer[layers.get(item_id, 0)].append(item_id)

    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    item_set = set(item_order)
    for edge in edges:
        if edge.source in item_set and edge.target in item_set:
            outgoing[edge.source].append(edge.target)
            incoming[edge.target].append(edge.source)

    layers_sorted = sorted(by_layer)
    positions = _positions(by_layer)

    def barycenter(item_id: str, refs: list[str]) -> float | None:
        values = [positions[ref] for ref in refs if ref in positions]
        if not values:
            return None
        return sum(values) / len(values)

    def sort_layer(layer: int, refs: dict[str, list[str]]) -> None:
        current = list(by_layer[layer])
        current_pos = {item_id: index for index, item_id in enumerate(current)}

        def key(item_id: str) -> tuple[float, int]:
            bary = barycenter(item_id, refs.get(item_id, []))
            if bary is None:
                bary = float(current_pos[item_id])
            return (bary, item_position[item_id])

        by_layer[layer] = sorted(current, key=key)

    for _ in range(4):
        positions = _positions(by_layer)
        for layer in layers_sorted[1:]:
            sort_layer(layer, incoming)
        positions = _positions(by_layer)
        for layer in reversed(layers_sorted[:-1]):
            sort_layer(layer, outgoing)

    return dict(sorted(by_layer.items()))


def _positions(by_layer: dict[int, list[str]]) -> dict[str, float]:
    positions: dict[str, float] = {}
    for item_ids in by_layer.values():
        for index, item_id in enumerate(item_ids):
            positions[item_id] = float(index)
    return positions


def _box_around(boxes: list[Box], config: _LayoutConfig) -> Box:
    min_x = min(box.x for box in boxes) - config.group_padding_x
    min_y = min(box.y for box in boxes) - config.group_padding_top
    max_x = max(box.x + box.width for box in boxes) + config.group_padding_x
    max_y = max(box.y + box.height for box in boxes) + config.group_padding_bottom
    return Box(min_x, min_y, max_x - min_x, max_y - min_y)


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
