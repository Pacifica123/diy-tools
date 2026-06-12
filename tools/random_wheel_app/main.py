from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def load_stylesheet() -> str:
    style_path = Path(__file__).parent / "app" / "ui" / "styles.qss"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return ""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Random Wheel")
    app.setStyleSheet(load_stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
