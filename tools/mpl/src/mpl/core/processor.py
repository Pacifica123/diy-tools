from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .parser import ParserOptions, parse_mermaid
from .svg_renderer import render_svg


@dataclass(slots=True)
class ProcessOptions:
    render_svg: bool = True
    strict: bool = False


def process_mermaid(source: str, options: ProcessOptions | None = None) -> dict[str, Any]:
    options = options or ProcessOptions()
    diagram = parse_mermaid(source, ParserOptions(strict=options.strict))
    payload: dict[str, Any] = {
        "ok": True,
        "diagram": diagram.to_dict(),
        "warnings": list(diagram.warnings),
    }
    if options.render_svg:
        payload["svg"] = render_svg(diagram)
    return payload
