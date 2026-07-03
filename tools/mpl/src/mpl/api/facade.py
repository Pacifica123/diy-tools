from __future__ import annotations

from pathlib import Path
from typing import Any

from mpl.core import ProcessOptions, process_mermaid


def process_text(source: str, *, render: bool = True, strict: bool = False) -> dict[str, Any]:
    return process_mermaid(source, ProcessOptions(render_svg=render, strict=strict))


def process_file(path: str | Path, *, render: bool = True, strict: bool = False) -> dict[str, Any]:
    source = Path(path).read_text(encoding="utf-8")
    return process_text(source, render=render, strict=strict)
