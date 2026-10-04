from __future__ import annotations

import sys
from pathlib import Path

MISSING_GUI_MESSAGE = """Не удалось запустить «Колесо рандома»: не найдена библиотека PySide6 (нужна для окна).
Причина: {reason}
Установите зависимость командой:
    "{python}" -m pip install -r "{requirements}"
Если система запрещает pip (Arch Linux и похожие): поставьте пакет pyside6
средствами дистрибутива, например: sudo pacman -S pyside6
Затем запустите инструмент ещё раз."""


def load_stylesheet() -> str:
    style_path = Path(__file__).parent / "app" / "ui" / "styles.qss"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return ""


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication

        from app.ui.main_window import MainWindow
    except ImportError as exc:
        if not (exc.name or "").startswith("PySide6"):
            raise
        requirements = Path(__file__).resolve().parent / "requirements.txt"
        print(
            MISSING_GUI_MESSAGE.format(reason=exc, python=sys.executable or "python", requirements=requirements),
            file=sys.stderr,
        )
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("Random Wheel")
    app.setStyleSheet(load_stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
