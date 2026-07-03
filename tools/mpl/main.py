from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--cli":
        from mpl.cli import main as cli_main
        return cli_main(argv[1:])
    if argv and argv[0] in {"--help", "-h"}:
        print("mpl — Mermaid Processor Lite")
        print("GUI: python main.py")
        print("CLI: python main.py --cli --input examples/input/basic_flow.mmd --svg out.svg --ast out.json")
        return 0
    from mpl.gui.qt_app import main as gui_main
    return gui_main([str(ROOT / "main.py"), *argv])


if __name__ == "__main__":
    raise SystemExit(main())
