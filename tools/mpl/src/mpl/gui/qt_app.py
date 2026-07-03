from __future__ import annotations

import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from mpl.api import process_text


_SAMPLE = """flowchart TD
    A[Пишем Mermaid] --> B{Парсер понял?}
    B -- да --> C[Строим AST]
    B -- нет --> D[Показываем warnings]
    C --> E[Рисуем SVG-превью]
"""


def _load_qt():
    try:
        from PySide6.QtCore import QByteArray, Qt
        from PySide6.QtSvgWidgets import QSvgWidget
        from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget
        return {
            "binding": "PySide6",
            "QApplication": QApplication,
            "QByteArray": QByteArray,
            "QFileDialog": QFileDialog,
            "QHBoxLayout": QHBoxLayout,
            "QLabel": QLabel,
            "QMainWindow": QMainWindow,
            "QMessageBox": QMessageBox,
            "QPlainTextEdit": QPlainTextEdit,
            "QPushButton": QPushButton,
            "QSplitter": QSplitter,
            "QSvgWidget": QSvgWidget,
            "QVBoxLayout": QVBoxLayout,
            "QWidget": QWidget,
            "Qt": Qt,
        }
    except Exception:
        from PyQt6.QtCore import QByteArray, Qt
        from PyQt6.QtSvgWidgets import QSvgWidget
        from PyQt6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget
        return {
            "binding": "PyQt6",
            "QApplication": QApplication,
            "QByteArray": QByteArray,
            "QFileDialog": QFileDialog,
            "QHBoxLayout": QHBoxLayout,
            "QLabel": QLabel,
            "QMainWindow": QMainWindow,
            "QMessageBox": QMessageBox,
            "QPlainTextEdit": QPlainTextEdit,
            "QPushButton": QPushButton,
            "QSplitter": QSplitter,
            "QSvgWidget": QSvgWidget,
            "QVBoxLayout": QVBoxLayout,
            "QWidget": QWidget,
            "Qt": Qt,
        }


class MainWindow:
    def __init__(self, qt: dict):
        self.qt = qt
        QMainWindow = qt["QMainWindow"]
        QWidget = qt["QWidget"]
        QVBoxLayout = qt["QVBoxLayout"]
        QHBoxLayout = qt["QHBoxLayout"]
        QSplitter = qt["QSplitter"]
        QPushButton = qt["QPushButton"]
        QPlainTextEdit = qt["QPlainTextEdit"]
        QLabel = qt["QLabel"]
        QSvgWidget = qt["QSvgWidget"]
        Qt = qt["Qt"]

        self.window = QMainWindow()
        self.window.setWindowTitle("mpl — Mermaid Processor Lite")
        self.window.resize(1120, 720)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        top = QHBoxLayout()
        self.render_button = QPushButton("Отрисовать")
        self.open_button = QPushButton("Открыть .mmd")
        self.save_svg_button = QPushButton("Сохранить SVG")
        self.status = QLabel(f"Qt: {qt['binding']}. PNG не обязателен: превью строится из SVG в памяти.")
        top.addWidget(self.render_button)
        top.addWidget(self.open_button)
        top.addWidget(self.save_svg_button)
        top.addWidget(self.status, 1)
        root_layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(_SAMPLE)
        self.preview = QSvgWidget()
        self.preview.setMinimumWidth(420)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.preview, 6)
        right_layout.addWidget(self.report, 2)
        splitter.addWidget(self.editor)
        splitter.addWidget(right)
        splitter.setSizes([480, 640])
        root_layout.addWidget(splitter, 1)
        self.window.setCentralWidget(root)

        self.last_svg = ""
        self.render_button.clicked.connect(self.render_current)
        self.open_button.clicked.connect(self.open_file)
        self.save_svg_button.clicked.connect(self.save_svg)
        self.render_current()

    def render_current(self) -> None:
        try:
            result = process_text(self.editor.toPlainText(), render=True)
            self.last_svg = result["svg"]
            self.preview.load(self.qt["QByteArray"](self.last_svg.encode("utf-8")))
            diagram = result["diagram"]
            report_lines = [
                f"nodes: {len(diagram['nodes'])}",
                f"edges: {len(diagram['edges'])}",
                f"groups: {len(diagram['groups'])}",
            ]
            if result.get("warnings"):
                report_lines.append("warnings:")
                report_lines.extend(f"- {item}" for item in result["warnings"])
            self.report.setPlainText("\n".join(report_lines))
        except Exception as exc:  # noqa: BLE001 - GUI boundary.
            self.report.setPlainText(f"Ошибка: {exc}")

    def open_file(self) -> None:
        path, _ = self.qt["QFileDialog"].getOpenFileName(self.window, "Открыть Mermaid", "", "Mermaid (*.mmd *.mermaid *.txt);;All files (*)")
        if not path:
            return
        self.editor.setPlainText(Path(path).read_text(encoding="utf-8"))
        self.render_current()

    def save_svg(self) -> None:
        if not self.last_svg:
            self.render_current()
        path, _ = self.qt["QFileDialog"].getSaveFileName(self.window, "Сохранить SVG", "diagram.svg", "SVG (*.svg)")
        if not path:
            return
        Path(path).write_text(self.last_svg, encoding="utf-8")
        self.status.setText(f"SVG сохранён: {path}")


def main(argv: list[str] | None = None) -> int:
    try:
        qt = _load_qt()
    except Exception as exc:  # noqa: BLE001 - friendly dependency message.
        print("mpl GUI требует PySide6 или PyQt6. Установи: pip install -r requirements.txt", file=sys.stderr)
        print(f"деталь: {exc}", file=sys.stderr)
        return 5
    app = qt["QApplication"](argv or sys.argv)
    window = MainWindow(qt)
    window.window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
