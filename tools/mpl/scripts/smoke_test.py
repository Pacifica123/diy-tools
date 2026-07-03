from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mpl.abi import run_contract_json  # noqa: E402
from mpl.api import process_text  # noqa: E402
from mpl.cli import main as cli_main  # noqa: E402


SAMPLE = """flowchart LR
    A[Русский вход] -->|да| B{Проверка}
    B -- ок --> C((SVG))
    B -. warning .-> D[Отчёт]
"""


CYCLE_SAMPLE = """flowchart TD
    A[Старт] --> B[Проверка]
    B --> C[Исправление]
    C --> A
"""

GROUP_EDGE_SAMPLE = """flowchart TD
    ToolShelf[DIY tool shelf]
    subgraph MPL
    MplGui[Qt GUI]
    MplCore[core parser]
    MplGui --> MplCore
    end
    ToolShelf --> MPL
"""

FANOUT_SAMPLE = """flowchart TD
    ToolCapsule[tool capsule]
    ToolCapsule --> Readme[README.md]
    ToolCapsule --> ToolIni[tool.ini]
    ToolCapsule --> RunBat[run.bat]
    ToolCapsule --> RunSh[run.sh]
    ToolCapsule --> Src[src]
    ToolCapsule --> Examples[examples]
"""


def main() -> int:
    result = process_text(SAMPLE, render=True)
    diagram = result["diagram"]
    assert result["ok"] is True
    assert len(diagram["nodes"]) == 4, diagram
    assert len(diagram["edges"]) == 3, diagram
    assert "Русский вход" in result["svg"]
    assert "marker-end" in result["svg"]
    assert "#ffffff" in result["svg"]
    assert ".node-decision" in result["svg"]

    cycle_result = process_text(CYCLE_SAMPLE, render=True)
    size_match = re.search(r'width="([0-9]+)" height="([0-9]+)"', cycle_result["svg"])
    assert size_match is not None
    assert int(size_match.group(1)) < 900
    assert int(size_match.group(2)) < 900
    assert " C " not in cycle_result["svg"], "edge routing should use orthogonal line segments, not cubic splines"

    group_result = process_text(GROUP_EDGE_SAMPLE, render=True)
    group_svg = group_result["svg"]
    assert len(group_result["diagram"]["groups"]) == 1
    assert not any(node["id"] == "MPL" and node["label"] == "MPL" for node in group_result["diagram"]["nodes"])
    assert group_svg.index('<g class="groups">') < group_svg.index('<g class="edges">') < group_svg.index('<g class="edge-labels">') < group_svg.index('<g class="nodes">') < group_svg.index('<g class="node-labels">')

    fanout_result = process_text(FANOUT_SAMPLE, render=True)
    fanout_svg = fanout_result["svg"]
    first_segment_x_values = re.findall(r'M ([0-9.]+) [0-9.]+ L \1', fanout_svg)
    assert len(set(first_segment_x_values)) >= 3, "fan-out edges should not all leave the source at one identical port"

    abi_result = json.loads(run_contract_json(json.dumps({"source": SAMPLE, "render": False}, ensure_ascii=False)))
    assert abi_result["abi"]["name"] == "mpl-json"
    assert "svg" not in abi_result

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        input_path = tmp / "diagram.mmd"
        ast_path = tmp / "diagram.ast.json"
        svg_path = tmp / "diagram.svg"
        input_path.write_text(SAMPLE, encoding="utf-8")
        code = cli_main(["--input", str(input_path), "--ast", str(ast_path), "--svg", str(svg_path)])
        assert code == 0
        assert ast_path.is_file()
        assert svg_path.is_file()
        ast = json.loads(ast_path.read_text(encoding="utf-8"))
        assert ast["direction"] == "LR"
        assert len(ast["nodes"]) == 4
    print("smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
