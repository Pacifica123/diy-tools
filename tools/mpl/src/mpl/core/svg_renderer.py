from __future__ import annotations

from html import escape

from .layout import Box, build_layout, wrapped_label_lines
from .model import Diagram, Edge, Node


class SvgRenderError(ValueError):
    pass


def render_svg(diagram: Diagram) -> str:
    layout = build_layout(diagram)
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width:.0f}" height="{layout.height:.0f}" '
        f'viewBox="0 0 {layout.width:.0f} {layout.height:.0f}" role="img">'
    )
    parts.append("<defs>")
    parts.append(
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#263238" /></marker>'
    )
    parts.append("</defs>")
    parts.append("<style><![CDATA[")
    parts.append(
        "svg{background:#f8fafc;font-family:Arial,'DejaVu Sans',sans-serif}"
        ".group{fill:#eef2ff;stroke:#94a3b8;stroke-width:1.2;stroke-dasharray:6 5}"
        ".group-label{font-size:13px;fill:#334155;font-weight:600}"
        ".node{fill:#ffffff;stroke:#263238;stroke-width:1.4}"
        ".node-alt{fill:#f1f5f9}"
        ".edge{fill:none;stroke:#263238;stroke-width:1.4}"
        ".edge.thick{stroke-width:2.8}"
        ".edge.dotted{stroke-dasharray:5 5}"
        ".label-bg{fill:#f8fafc;stroke:#cbd5e1;stroke-width:.7}"
        ".text{font-size:14px;fill:#111827;text-anchor:middle;dominant-baseline:middle}"
        ".edge-label{font-size:12px;fill:#1f2937;text-anchor:middle;dominant-baseline:middle}"
    )
    parts.append("]]></style>")

    for group_id, box in layout.group_boxes.items():
        group = diagram.groups[group_id]
        parts.append(
            f'<rect class="group" x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" rx="14" />'
        )
        parts.append(
            f'<text class="group-label" x="{box.x + 12:.1f}" y="{box.y + 20:.1f}">{escape(group.label)}</text>'
        )

    for edge in diagram.edges:
        source_box = _endpoint_box(edge.source, layout)
        target_box = _endpoint_box(edge.target, layout)
        if source_box is None or target_box is None:
            continue
        parts.append(_render_edge(edge, source_box, target_box, layout.direction))

    for node_id, node in diagram.nodes.items():
        parts.append(_render_node(node, layout.node_boxes[node_id]))

    if diagram.warnings:
        warning_text = f"warnings: {len(diagram.warnings)}"
        parts.append(f'<text x="12" y="{layout.height - 12:.1f}" font-size="11" fill="#64748b">{escape(warning_text)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _endpoint_box(item_id: str, layout) -> Box | None:
    return layout.node_boxes.get(item_id) or layout.group_boxes.get(item_id)


def _render_edge(edge: Edge, source: Box, target: Box, direction: str) -> str:
    x1, y1, x2, y2 = _edge_points(source, target, direction)
    if direction in {"LR", "RL"}:
        mid = (x1 + x2) / 2
        path = f"M {x1:.1f} {y1:.1f} C {mid:.1f} {y1:.1f}, {mid:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}"
    else:
        mid = (y1 + y2) / 2
        path = f"M {x1:.1f} {y1:.1f} C {x1:.1f} {mid:.1f}, {x2:.1f} {mid:.1f}, {x2:.1f} {y2:.1f}"
    classes = "edge " + edge.style
    marker_end = ' marker-end="url(#arrow)"' if edge.directed else ""
    marker_start = ' marker-start="url(#arrow)"' if edge.bidirectional else ""
    label_x = (x1 + x2) / 2
    label_y = (y1 + y2) / 2 - 8
    label = ""
    if edge.label:
        safe = escape(edge.label)
        width = max(34, min(180, len(edge.label) * 7 + 18))
        label = (
            f'<rect class="label-bg" x="{label_x - width / 2:.1f}" y="{label_y - 10:.1f}" width="{width:.1f}" height="20" rx="6" />'
            f'<text class="edge-label" x="{label_x:.1f}" y="{label_y:.1f}">{safe}</text>'
        )
    return f'<path class="{classes}" d="{path}"{marker_start}{marker_end} />{label}'


def _edge_points(source: Box, target: Box, direction: str) -> tuple[float, float, float, float]:
    if direction == "LR":
        return source.x + source.width, source.cy, target.x, target.cy
    if direction == "RL":
        return source.x, source.cy, target.x + target.width, target.cy
    if direction == "BT":
        return source.cx, source.y, target.cx, target.y + target.height
    return source.cx, source.y + source.height, target.cx, target.y


def _render_node(node: Node, box: Box) -> str:
    shape = node.shape
    if shape == "diamond":
        points = [
            (box.cx, box.y),
            (box.x + box.width, box.cy),
            (box.cx, box.y + box.height),
            (box.x, box.cy),
        ]
        point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        body = f'<polygon class="node" points="{point_text}" />'
    elif shape == "circle":
        body = f'<ellipse class="node" cx="{box.cx:.1f}" cy="{box.cy:.1f}" rx="{box.width / 2:.1f}" ry="{box.height / 2:.1f}" />'
    elif shape == "round":
        body = f'<rect class="node" x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" rx="24" />'
    elif shape in {"subroutine", "cylinder", "hex", "parallelogram", "parallelogram_alt"}:
        body = _render_special_shape(shape, box)
    else:
        body = f'<rect class="node" x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" rx="9" />'
    return body + _render_node_text(node.label, box)


def _render_special_shape(shape: str, box: Box) -> str:
    if shape == "subroutine":
        inner_left = box.x + 12
        inner_right = box.x + box.width - 12
        return (
            f'<rect class="node node-alt" x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" rx="5" />'
            f'<line x1="{inner_left:.1f}" y1="{box.y:.1f}" x2="{inner_left:.1f}" y2="{box.y + box.height:.1f}" stroke="#263238" />'
            f'<line x1="{inner_right:.1f}" y1="{box.y:.1f}" x2="{inner_right:.1f}" y2="{box.y + box.height:.1f}" stroke="#263238" />'
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
