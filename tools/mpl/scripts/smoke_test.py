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
from mpl.core.layout import build_layout  # noqa: E402
from mpl.core.parser import parse_mermaid  # noqa: E402


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


EXTERNAL_REF_SAMPLE = """flowchart TD
    Outside[external node]
    subgraph G
    Inside[inside node]
    Inside --> Outside
    end
"""


TWO_GROUP_SAMPLE = """flowchart TD
    subgraph One
    A1[one a] --> A2[one b] --> A3[one c]
    end
    subgraph Two
    B1[two a] --> B2[two b]
    end
"""


CLUSTER_SAMPLE = """flowchart TD
    A[external start] --> B[external middle]
    subgraph G
    G1[group one] --> G2[group two] --> G3[group three]
    end
    B --> G
    G --> C[external finish]
    C --> A
"""


def _boxes_overlap(left, right) -> bool:
    return not (
        left.x + left.width <= right.x
        or right.x + right.width <= left.x
        or left.y + left.height <= right.y
        or right.y + right.height <= left.y
    )

def _box_contains(outer, inner) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and outer.x + outer.width >= inner.x + inner.width
        and outer.y + outer.height >= inner.y + inner.height
    )


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
    fanout_size = re.search(r'width="([0-9]+)" height="([0-9]+)"', fanout_svg)
    assert fanout_size is not None
    assert int(fanout_size.group(1)) < 1300, "fan-out layers should wrap instead of creating a very wide canvas"

    external_diagram = parse_mermaid(EXTERNAL_REF_SAMPLE)
    external_nodes = {node["id"]: node for node in external_diagram.to_dict()["nodes"]}
    assert external_nodes["Outside"]["group"] is None, "bare external references inside a subgraph must not adopt that subgraph"
    assert external_nodes["Inside"]["group"] == "G"

    two_group_layout = build_layout(parse_mermaid(TWO_GROUP_SAMPLE))
    group_boxes = list(two_group_layout.group_boxes.values())
    assert len(group_boxes) == 2
    assert not _boxes_overlap(group_boxes[0], group_boxes[1]), "top-level groups should not overlap visually"

    cluster_diagram = parse_mermaid(CLUSTER_SAMPLE)
    cluster_layout = build_layout(cluster_diagram)
    group_box = cluster_layout.group_boxes["G"]
    assert not _box_contains(group_box, cluster_layout.node_boxes["A"]), "group box must not cover external source-order nodes"
    assert not _box_contains(group_box, cluster_layout.node_boxes["B"]), "group box must not cover external nodes before the group"
    assert not _box_contains(group_box, cluster_layout.node_boxes["C"]), "group box must not cover external nodes after the group"
    cluster_svg = process_text(CLUSTER_SAMPLE, render=True)["svg"]
    assert "-42.0" not in cluster_svg, "back-edge routing should not use far negative side lanes"

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
