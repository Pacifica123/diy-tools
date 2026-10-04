from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Diagram, Edge, Group, Node


_HEADER_RE = re.compile(r"^(graph|flowchart)\s+(TD|TB|BT|LR|RL)\s*$", re.IGNORECASE)
_SUBGRAPH_RE = re.compile(r"^subgraph\s+(.+)$", re.IGNORECASE)
_EDGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(.+?)\s*(<-->|-->|---|-\.->|==>)\s*\|(.+?)\|\s*(.+)$"),
    re.compile(r"^(.+?)\s*(?<![-<])--\s*(?![->])(.+?)\s*-->\s*(.+)$"),
    re.compile(r"^(.+?)\s*-\.\s*(?!-)(.+?)\s*\.->\s*(.+)$"),
    re.compile(r"^(.+?)\s*(?<!=)==\s*(?![=>])(.+?)\s*==>\s*(.+)$"),
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

        parsed_edges = _parse_edge_chain(statement)
        if parsed_edges:
            current_group = group_stack[-1] if group_stack else None
            for left, operator, label, right in parsed_edges:
                source_node = _parse_edge_node(left, current_group, diagram)
                target_node = _parse_edge_node(right, current_group, diagram)
                if not _is_bare_group_reference(left, diagram):
                    diagram.add_node(source_node)
                if not _is_bare_group_reference(right, diagram):
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


def _parse_edge_chain(statement: str) -> list[tuple[str, str, str, str]]:
    """Split ``A --> B -- да --> C`` into consecutive edges.

    Before 0.2.0 a chain was silently misread as one edge ``A -> C`` with the
    label ``> B`` and the middle node was lost. Arrows are searched only
    outside of brackets and quotes, so ``A[x --> y] --> B`` stays one edge.
    """
    nodes, links = _split_chain(statement, _mask_nested(statement))
    return [(nodes[index], operator, label, nodes[index + 1]) for index, (operator, label) in enumerate(links)]


def _split_chain(text: str, masked: str) -> tuple[list[str], list[tuple[str, str]]]:
    found = _match_edge(masked)
    if found is None:
        return [text.strip()], []
    left, operator, label, right = found
    left_nodes, left_links = _split_chain(text[left[0]:left[1]], masked[left[0]:left[1]])
    right_nodes, right_links = _split_chain(text[right[0]:right[1]], masked[right[0]:right[1]])
    label_text = _clean_label(text[label[0]:label[1]]) if label is not None else ""
    return left_nodes + right_nodes, left_links + [(operator, label_text)] + right_links


def _match_edge(masked: str) -> tuple[tuple[int, int], str, tuple[int, int] | None, tuple[int, int]] | None:
    for index, pattern in enumerate(_EDGE_PATTERNS):
        match = pattern.match(masked)
        if not match:
            continue
        if index in (1, 2, 3):
            operator = "-->" if index == 1 else "-.->" if index == 2 else "==>"
            return match.span(1), operator, match.span(2), match.span(3)
        if index == 0:
            return match.span(1), match.group(2), match.span(3), match.span(4)
        return match.span(1), match.group(2), None, match.span(3)
    return None


def _mask_nested(text: str) -> str:
    """Hide bracket and quote contents so that arrows inside labels are not links.

    The result has the same length as ``text``; if brackets or quotes are not
    balanced the text is returned unchanged (old tolerant behaviour).
    """
    closing = {"[": "]", "(": ")", "{": "}"}
    result: list[str] = []
    stack: list[str] = []
    quote: str | None = None
    for ch in text:
        if quote:
            result.append("_")
            if ch == quote:
                quote = None
            continue
        if ch == '"':
            quote = ch
            result.append("_")
            continue
        if ch in closing:
            stack.append(closing[ch])
            result.append("_")
            continue
        if stack:
            if ch == stack[-1]:
                stack.pop()
            result.append("_")
            continue
        result.append(ch)
    if stack or quote:
        return text
    return "".join(result)


def _parse_edge_node(raw: str, group_id: str | None, diagram: Diagram) -> Node:
    node = _parse_node(raw, group_id)
    if group_id is None:
        return node
    old = diagram.nodes.get(node.id)
    if old is None:
        return node
    # A bare reference from inside a subgraph should not silently pull an
    # already declared external node into that subgraph. Example:
    #
    #   A[outside]
    #   subgraph G
    #   B --> A
    #   end
    #
    # In v4 this changed A.group to G and made group boxes enormous.
    if _is_bare_node_reference(raw):
        node.group = old.group
    return node


def _is_bare_node_reference(raw: str) -> bool:
    text = raw.strip().strip('"').strip("'")
    return bool(text) and not any(ch in text for ch in "[](){}")



def _is_bare_group_reference(raw: str, diagram: Diagram) -> bool:
    text = raw.strip().strip('"').strip("'")
    if any(ch in text for ch in "[](){}"):
        return False
    return text in diagram.groups


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
