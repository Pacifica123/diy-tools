from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Diagram, Edge, Group, Node


_HEADER_RE = re.compile(r"^(graph|flowchart)\s+(TD|TB|BT|LR|RL)\s*$", re.IGNORECASE)
_SUBGRAPH_RE = re.compile(r"^subgraph\s+(.+)$", re.IGNORECASE)
_EDGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(.+?)\s*(<-->|-->|---|-\.->|==>)\s*\|(.+?)\|\s*(.+)$"),
    re.compile(r"^(.+?)\s*--\s*(.+?)\s*-->\s*(.+)$"),
    re.compile(r"^(.+?)\s*-\.\s*(.+?)\s*\.->\s*(.+)$"),
    re.compile(r"^(.+?)\s*==\s*(.+?)\s*==>\s*(.+)$"),
    re.compile(r"^(.+?)\s*(<-->|-->|---|-\.->|==>)\s*(.+)$"),
)

_SHAPES: tuple[tuple[str, str], ...] = (
    (r"^(.+?)\s*\[\[(.+)\]\]$", "subroutine"),
    (r"^(.+?)\s*\[\((.+)\)\]$", "cylinder"),
    (r"^(.+?)\s*\(\((.+)\)\)$", "circle"),
    (r"^(.+?)\s*\{\{(.+)\}\}$", "hex"),
    (r"^(.+?)\s*\{(.+)\}$", "diamond"),
    (r"^(.+?)\s*\[/(.+)/\]$", "parallelogram"),
    (r"^(.+?)\s*\[\\(.+)\\\]$", "parallelogram_alt"),
    (r"^(.+?)\s*\[(.+)\]$", "rect"),
    (r"^(.+?)\s*\((.+)\)$", "round"),
)


@dataclass(slots=True)
class ParserOptions:
    strict: bool = False


class MermaidParseError(ValueError):
    pass


def parse_mermaid(source: str, options: ParserOptions | None = None) -> Diagram:
    options = options or ParserOptions()
    diagram = Diagram()
    group_stack: list[str] = []
    saw_header = False

    for line_no, statement in _iter_statements(source):
        if not statement:
            continue
        header = _HEADER_RE.match(statement)
        if header:
            diagram.kind = header.group(1).lower()
            diagram.direction = header.group(2).upper().replace("TB", "TD")
            saw_header = True
            continue

        subgraph = _SUBGRAPH_RE.match(statement)
        if subgraph:
            group = _parse_group(subgraph.group(1), diagram, group_stack[-1] if group_stack else None)
            diagram.groups[group.id] = group
            group_stack.append(group.id)
            continue

        if statement.lower() == "end":
            if group_stack:
                group_stack.pop()
            else:
                _warn_or_raise(diagram, options, line_no, "лишний end без subgraph")
            continue

        lowered = statement.lower()
        if lowered.startswith(("class ", "classdef ", "style ", "linkstyle ", "click ")):
            diagram.warnings.append(f"строка {line_no}: инструкция пока пропущена: {statement}")
            continue

        parsed_edge = _parse_edge(statement)
        if parsed_edge is not None:
            left, operator, label, right = parsed_edge
            source_node = _parse_node(left, group_stack[-1] if group_stack else None)
            target_node = _parse_node(right, group_stack[-1] if group_stack else None)
            diagram.add_node(source_node)
            diagram.add_node(target_node)
            diagram.add_edge(_edge_from_operator(source_node.id, target_node.id, operator, label))
            continue

        parsed_node = _parse_node(statement, group_stack[-1] if group_stack else None)
        if parsed_node.id:
            diagram.add_node(parsed_node)
        else:
            _warn_or_raise(diagram, options, line_no, "не удалось разобрать строку")

    if not saw_header:
        diagram.warnings.append("заголовок graph/flowchart не найден; использовано flowchart TD")
    if group_stack:
        diagram.warnings.append("есть незакрытые subgraph-блоки: " + ", ".join(group_stack))
    return diagram


def _iter_statements(source: str):
    cleaned = source.replace("\ufeff", "")
    for line_no, raw in enumerate(cleaned.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("%%") or line.startswith("```"):
            continue
        comment_index = line.find(" %%")
        if comment_index >= 0:
            line = line[:comment_index].rstrip()
        for statement in _split_semicolon(line):
            statement = statement.strip()
            if statement:
                yield line_no, statement


def _split_semicolon(line: str) -> list[str]:
    result: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    depth = 0
    pairs_open = "[({"
    pairs_close = "])}"
    for ch in line:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in {'"', "'"}:
            quote = ch
            buf.append(ch)
            continue
        if ch in pairs_open:
            depth += 1
            buf.append(ch)
            continue
        if ch in pairs_close and depth:
            depth -= 1
            buf.append(ch)
            continue
        if ch == ";" and depth == 0:
            result.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    result.append("".join(buf))
    return result


def _parse_group(raw: str, diagram: Diagram, parent: str | None) -> Group:
    node = _parse_node(raw, parent)
    if node.id == node.label and " " in raw.strip():
        group_id = f"group_{len(diagram.groups) + 1}"
        return Group(id=group_id, label=_clean_label(raw), parent=parent)
    return Group(id=node.id or f"group_{len(diagram.groups) + 1}", label=node.label or node.id, parent=parent)


def _parse_edge(statement: str) -> tuple[str, str, str, str] | None:
    for index, pattern in enumerate(_EDGE_PATTERNS):
        match = pattern.match(statement)
        if not match:
            continue
        if index in (1, 2, 3):
            left, label, right = match.groups()
            operator = "-->" if index == 1 else "-.->" if index == 2 else "==>"
            return left.strip(), operator, _clean_label(label), right.strip()
        left, operator, *rest = match.groups()
        if len(rest) == 2:
            label, right = rest
        else:
            label, right = "", rest[0]
        return left.strip(), operator, _clean_label(label), right.strip()
    return None


def _edge_from_operator(source: str, target: str, operator: str, label: str) -> Edge:
    return Edge(
        source=source,
        target=target,
        label=label,
        directed=operator != "---",
        bidirectional=operator == "<-->",
        style="dotted" if operator == "-.->" else "thick" if operator == "==>" else "normal",
    )


def _parse_node(raw: str, group_id: str | None) -> Node:
    text = raw.strip()
    for pattern_text, shape in _SHAPES:
        match = re.match(pattern_text, text)
        if match:
            node_id, label = match.groups()
            return Node(id=_clean_id(node_id), label=_clean_label(label), shape=shape, group=group_id)
    return Node(id=_clean_id(text), label=_clean_label(text), shape="rect", group=group_id)


def _clean_id(value: str) -> str:
    value = value.strip().strip('"').strip("'")
    value = re.sub(r"\s+", "_", value)
    return value


def _clean_label(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.replace("<br>", "\n").replace("<br/>", "\n")


def _warn_or_raise(diagram: Diagram, options: ParserOptions, line_no: int, message: str) -> None:
    final = f"строка {line_no}: {message}"
    if options.strict:
        raise MermaidParseError(final)
    diagram.warnings.append(final)
