from __future__ import annotations

import json
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


def main() -> int:
    result = process_text(SAMPLE, render=True)
    diagram = result["diagram"]
    assert result["ok"] is True
    assert len(diagram["nodes"]) == 4, diagram
    assert len(diagram["edges"]) == 3, diagram
    assert "Русский вход" in result["svg"]
    assert "marker-end" in result["svg"]

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
