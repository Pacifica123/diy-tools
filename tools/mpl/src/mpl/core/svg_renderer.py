from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from html import escape
from .layout import Box, Layout, build_layout, wrapped_label_lines
from .model import Diagram, Edge, Node


class SvgRenderError(ValueError):
    pass


@dataclass(slots=True)
class _RoutedEdge:
    path: str
    label_x: float
    label_y: float
    css_class: str
    marker_start: bool
    marker_end: bool
    label: str


def render_svg(diagram: Diagram) -> str:
    layout = build_layout(diagram)
    routed_edges = _route_edges(diagram, layout)
    node_shapes: list[str] = []
    node_texts: list[str] = []
    edge_paths: list[str] = []
    edge_labels: list[str] = []

    for edge, routed in routed_edges:
        marker_end = ' marker-end="url(#arrow)"' if routed.marker_end else ""
        marker_start = ' marker-start="url(#arrow)"' if routed.marker_start else ""
        edge_paths.append(f'<path class="{routed.css_class}" d="{routed.path}"{marker_start}{marker_end} />')
        if routed.label:
            edge_labels.append(_render_edge_label(routed.label, routed.label_x, routed.label_y))

    for node_id, node in diagram.nodes.items():
        shape, text = _render_node_parts(node, layout.node_boxes[node_id])
        node_shapes.append(shape)
        node_texts.append(text)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width:.0f}" height="{layout.height:.0f}" '
        f'viewBox="0 0 {layout.width:.0f} {layout.height:.0f}" role="img">'
    )
    parts.append("<defs>")
    parts.append(
        '<marker id="arrow" viewBox="0 0 10 10" refX="8.8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#1f2937" /></marker>'
    )
    parts.append("</defs>")
    parts.append("<style><![CDATA[")
    parts.append(_stylesheet())
    parts.append("]]></style>")

    # Explicit z-order. The order is part of the renderer contract because it
    # keeps edges from visually eating nodes and keeps edge labels legible.
    parts.append(f'<rect class="canvas" x="0" y="0" width="{layout.width:.0f}" height="{layout.height:.0f}" />')
    parts.append('<g class="groups">')
    for group_id, box in layout.group_boxes.items():
        group = diagram.groups[group_id]
        parts.append(
            f'<rect class="group" x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" rx="16" />'
        )
        parts.append(
            f'<text class="group-label" x="{box.x + 14:.1f}" y="{box.y + 22:.1f}">{escape(group.label)}</text>'
        )
    parts.append('</g>')
    parts.append('<g class="edges">')
    parts.extend(edge_paths)
    parts.append('</g>')
    parts.append('<g class="edge-labels">')
    parts.extend(edge_labels)
    parts.append('</g>')
    parts.append('<g class="nodes">')
    parts.extend(node_shapes)
    parts.append('</g>')
    parts.append('<g class="node-labels">')
    parts.extend(node_texts)
    parts.append('</g>')

    if diagram.warnings:
        warning_text = f"warnings: {len(diagram.warnings)}"
        parts.append(f'<text x="12" y="{layout.height - 12:.1f}" font-size="11" fill="#64748b">{escape(warning_text)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _stylesheet() -> str:
    return (
        "svg{background:#ffffff;font-family:Arial,'DejaVu Sans',sans-serif}"
        ".canvas{fill:#ffffff}"
        ".group{fill:#f5faff;fill-opacity:.72;stroke:#5d8fc2;stroke-width:1.35;stroke-dasharray:7 5}"
        ".group-label{font-size:13px;fill:#14324f;font-weight:600}"
        ".node{fill:#ffffff;stroke:#1f2937;stroke-width:1.45}"
        ".node-alt{fill:#fbfdff}"
        ".node-decision{fill:#fff7df;stroke:#1f2937;stroke-width:1.45}"
        ".edge{fill:none;stroke:#334155;stroke-width:1.55;stroke-linecap:square;stroke-linejoin:miter}"
        ".edge.thick{stroke-width:2.75}"
        ".edge.dotted{stroke-dasharray:6 6}"
        ".label-bg{fill:#ffffff;stroke:#7c8da3;stroke-width:.9}"
        ".text{font-size:14px;fill:#111827;text-anchor:middle;dominant-baseline:middle}"
        ".edge-label{font-size:12px;fill:#111827;text-anchor:middle;dominant-baseline:middle}"
    )


def _endpoint_box(item_id: str, layout: Layout) -> Box | None:
    return layout.node_boxes.get(item_id) or layout.group_boxes.get(item_id)


def _route_edges(diagram: Diagram, layout: Layout) -> list[tuple[Edge, _RoutedEdge]]:
    endpoint_boxes = {**layout.group_boxes, **layout.node_boxes}
    routeable: list[tuple[int, Edge]] = []
    for index, edge in enumerate(diagram.edges):
        if edge.source in endpoint_boxes and edge.target in endpoint_boxes:
            routeable.append((index, edge))

    source_offsets, target_offsets = _port_offsets(routeable, endpoint_boxes, layout.direction)
    routed: list[tuple[Edge, _RoutedEdge]] = []
    for index, edge in routeable:
        source = endpoint_boxes[edge.source]
        target = endpoint_boxes[edge.target]
        routed.append((edge, _render_edge(edge, source, target, layout.direction, source_offsets[index], target_offsets[index])))
    return routed


def _port_offsets(
    indexed_edges: list[tuple[int, Edge]],
    boxes: dict[str, Box],
    direction: str,
) -> tuple[dict[int, float], dict[int, float]]:
    horizontal = direction in {"LR", "RL"}
    by_source: dict[str, list[tuple[int, Edge]]] = defaultdict(list)
    by_target: dict[str, list[tuple[int, Edge]]] = defaultdict(list)
    for item in indexed_edges:
        _, edge = item
        by_source[edge.source].append(item)
        by_target[edge.target].append(item)

    source_offsets: dict[int, float] = {}
    target_offsets: dict[int, float] = {}

    def center_for_target(item: tuple[int, Edge]) -> float:
        _, edge = item
        box = boxes[edge.target]
        return box.cy if horizontal else box.cx

    def center_for_source(item: tuple[int, Edge]) -> float:
        _, edge = item
        box = boxes[edge.source]
        return box.cy if horizontal else box.cx

    for source_id, items in by_source.items():
        span = (boxes[source_id].height if horizontal else boxes[source_id].width) * 0.70
        for slot, (index, _) in enumerate(sorted(items, key=center_for_target)):
            source_offsets[index] = _slot_offset(slot, len(items), span)
    for target_id, items in by_target.items():
        span = (boxes[target_id].height if horizontal else boxes[target_id].width) * 0.70
        for slot, (index, _) in enumerate(sorted(items, key=center_for_source)):
            target_offsets[index] = _slot_offset(slot, len(items), span)
    return source_offsets, target_offsets


def _slot_offset(slot: int, count: int, span: float) -> float:
    if count <= 1:
        return 0.0
    step = min(24.0, max(10.0, span / max(1, count - 1)))
    return (slot - (count - 1) / 2) * step


def _render_edge(edge: Edge, source: Box, target: Box, direction: str, source_offset: float, target_offset: float) -> _RoutedEdge:
    path, label_x, label_y = _orthogonal_path(source, target, direction, source_offset, target_offset)
    css_class = "edge " + edge.style
    return _RoutedEdge(
        path=path,
        label_x=label_x,
        label_y=label_y,
        css_class=css_class,
        marker_start=edge.bidirectional,
        marker_end=edge.directed,
        label=edge.label,
    )


def _orthogonal_path(source: Box, target: Box, direction: str, source_offset: float, target_offset: float) -> tuple[str, float, float]:
    """Route from the nearest sensible side of the boxes.

    v4 always used the nominal graph direction, so an upward edge in a TD graph
    left from the bottom of a node, walked around through a side lane, and often
    produced a long "where did this come from?" line. v5 chooses the side from
    actual geometry: below targets use bottom->top, above targets use top->bottom.
    """
    if direction in {"LR", "RL"}:
        if target.cx >= source.cx:
            x1, y1 = source.x + source.width, source.cy + source_offset
            x2, y2 = target.x, target.cy + target_offset
            return _orthogonal_horizontal(x1, y1, x2, y2, source, target, forward=True)
        x1, y1 = source.x, source.cy + source_offset
        x2, y2 = target.x + target.width, target.cy + target_offset
        return _orthogonal_horizontal(x1, y1, x2, y2, source, target, forward=False)

    if target.cy >= source.cy:
        x1, y1 = source.cx + source_offset, source.y + source.height
        x2, y2 = target.cx + target_offset, target.y
        return _orthogonal_vertical(x1, y1, x2, y2, source, target, forward=True)
    x1, y1 = source.cx + source_offset, source.y
    x2, y2 = target.cx + target_offset, target.y + target.height
    return _orthogonal_vertical(x1, y1, x2, y2, source, target, forward=False)


def _orthogonal_vertical(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    source: Box,
    target: Box,
    *,
    forward: bool,
) -> tuple[str, float, float]:
    # Keep every edge local. v5 used side lanes for back-edges, which often
    # produced long lines across the top or side of a group. That was technically
    # deterministic but unreadable. A compact dogleg is less clever and much more
    # predictable for hand-written architecture diagrams.
    if abs(x1 - x2) < 1.0:
        points = [(x1, y1), (x2, y2)]
        return _path_from_points(points), x1, (y1 + y2) / 2
    mid_y = y1 + (y2 - y1) / 2
    points = [(x1, y1), (x1, mid_y), (x2, mid_y), (x2, y2)]
    label_y = mid_y - 10 if y2 >= y1 else mid_y + 14
    return _path_from_points(points), (x1 + x2) / 2, label_y


def _orthogonal_horizontal(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    source: Box,
    target: Box,
    *,
    forward: bool,
) -> tuple[str, float, float]:
    if abs(y1 - y2) < 1.0:
        points = [(x1, y1), (x2, y2)]
        return _path_from_points(points), (x1 + x2) / 2, y1
    mid_x = x1 + (x2 - x1) / 2
    points = [(x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)]
    return _path_from_points(points), mid_x, (y1 + y2) / 2 - 10


def _side_lane_x(source: Box, target: Box) -> float:
    if source.cx <= target.cx:
        return min(source.x, target.x) - 42.0
    return max(source.x + source.width, target.x + target.width) + 42.0


def _side_lane_y(source: Box, target: Box) -> float:
    if source.cy <= target.cy:
        return min(source.y, target.y) - 42.0
    return max(source.y + source.height, target.y + target.height) + 42.0


def _path_from_points(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    compact: list[tuple[float, float]] = []
    for point in points:
        if compact and abs(compact[-1][0] - point[0]) < 0.1 and abs(compact[-1][1] - point[1]) < 0.1:
            continue
        compact.append(point)
    head, *tail = compact
    return "M " + f"{head[0]:.1f} {head[1]:.1f}" + "".join(f" L {x:.1f} {y:.1f}" for x, y in tail)


def _render_edge_label(label: str, x: float, y: float) -> str:
    safe = escape(label)
    width = max(36, min(210, len(label) * 7 + 20))
    return (
        f'<rect class="label-bg" x="{x - width / 2:.1f}" y="{y - 11:.1f}" width="{width:.1f}" height="22" rx="7" />'
        f'<text class="edge-label" x="{x:.1f}" y="{y:.1f}">{safe}</text>'
    )


def _render_node_parts(node: Node, box: Box) -> tuple[str, str]:
    shape = node.shape
    if shape == "diamond":
        points = [
            (box.cx, box.y),
            (box.x + box.width, box.cy),
            (box.cx, box.y + box.height),
            (box.x, box.cy),
        ]
        point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        body = f'<polygon class="node-decision" points="{point_text}" />'
    elif shape == "circle":
        body = f'<ellipse class="node" cx="{box.cx:.1f}" cy="{box.cy:.1f}" rx="{box.width / 2:.1f}" ry="{box.height / 2:.1f}" />'
    elif shape == "round":
        body = f'<rect class="node" x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" rx="24" />'
    elif shape in {"subroutine", "cylinder", "hex", "parallelogram", "parallelogram_alt"}:
        body = _render_special_shape(shape, box)
    else:
        body = f'<rect class="node" x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" rx="9" />'
    return body, _render_node_text(node.label, box)


def _render_special_shape(shape: str, box: Box) -> str:
    if shape == "subroutine":
        inner_left = box.x + 12
        inner_right = box.x + box.width - 12
        return (
            f'<rect class="node node-alt" x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" rx="5" />'
            f'<line x1="{inner_left:.1f}" y1="{box.y:.1f}" x2="{inner_left:.1f}" y2="{box.y + box.height:.1f}" stroke="#1f2937" />'
            f'<line x1="{inner_right:.1f}" y1="{box.y:.1f}" x2="{inner_right:.1f}" y2="{box.y + box.height:.1f}" stroke="#1f2937" />'
        )
    if shape == "cylinder":
        return (
            f'<rect class="node node-alt" x="{box.x:.1f}" y="{box.y + 8:.1f}" width="{box.width:.1f}" height="{box.height - 16:.1f}" />'
            f'<ellipse class="node" cx="{box.cx:.1f}" cy="{box.y + 8:.1f}" rx="{box.width / 2:.1f}" ry="8" />'
            f'<ellipse class="node" cx="{box.cx:.1f}" cy="{box.y + box.height - 8:.1f}" rx="{box.width / 2:.1f}" ry="8" />'
        )
    if shape == "hex":
        points = [
            (box.x + 16, box.y), (box.x + box.width - 16, box.y),
            (box.x + box.width, box.cy), (box.x + box.width - 16, box.y + box.height),
            (box.x + 16, box.y + box.height), (box.x, box.cy),
        ]
        return '<polygon class="node node-alt" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in points) + '" />'
    if shape in {"parallelogram", "parallelogram_alt"}:
        shift = 16 if shape == "parallelogram" else -16
        points = [(box.x + shift, box.y), (box.x + box.width + shift, box.y), (box.x + box.width - shift, box.y + box.height), (box.x - shift, box.y + box.height)]
        return '<polygon class="node node-alt" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in points) + '" />'
    return f'<rect class="node" x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" rx="9" />'


def _render_node_text(label: str, box: Box) -> str:
    lines = wrapped_label_lines(label)
    line_height = 17
    start_y = box.cy - (len(lines) - 1) * line_height / 2
    parts = []
    for index, line in enumerate(lines):
        parts.append(f'<text class="text" x="{box.cx:.1f}" y="{start_y + index * line_height:.1f}">{escape(line)}</text>')
    return "".join(parts)
