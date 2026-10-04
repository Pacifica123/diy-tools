from __future__ import annotations

import sys
from pathlib import Path

try:
    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow
except ImportError as exc:
    if (exc.name or "").split(".")[0] != "PySide6":
        raise
    print(
        "Не найдена библиотека PySide6 — без неё окно программы не запустится.\n"
        "Установите её командой:\n"
        f'    python -m pip install -r "{Path(__file__).resolve().with_name("requirements.txt")}"\n'
        "Если система запрещает pip (например, Arch Linux), поставьте пакет pyside6 из репозитория дистрибутива.\n"
        f"Подробности: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(1)


def load_stylesheet() -> str:
    style_path = Path(__file__).parent / "app" / "ui" / "styles.qss"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return ""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Anime Rerank Tournament")
    app.setStyleSheet(load_stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
