from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import SpinOptions, WheelItem
from app.domain.parser import ParseResult, parse_wheel_file
from app.domain.wheel import WheelEngine
from app.storage.autosave import has_autosave, read_autosave, write_autosave
from app.ui.wheel_window import WheelWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Колесо рандома")
        self.resize(980, 720)
        self.items: list[WheelItem] = []
        self.parse_result: ParseResult | None = None
        self.wheel_window: WheelWindow | None = None
        self._build_ui()
        self._refresh_autosave_button()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        title = QLabel("Колесо рандома")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "Загрузите TXT-словарик. Строка может быть просто вариантом или вариантом со значением через ':'. "
            "В режиме без значений все сегменты равны. В режиме со значениями площадь сегмента зависит от числа."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        top_row = QHBoxLayout()
        self.open_button = QPushButton("Выбрать TXT-файл")
        self.open_button.clicked.connect(self.open_file)
        top_row.addWidget(self.open_button)

        self.continue_button = QPushButton("Продолжить autosave")
        self.continue_button.clicked.connect(self.continue_autosave)
        top_row.addWidget(self.continue_button)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Без значения: все сегменты одинаковые", "equal")
        self.mode_combo.addItem("Со значением: сегмент пропорционален числу", "weighted")
        form.addRow("Режим:", self.mode_combo)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(500, 30000)
        self.duration_spin.setSingleStep(250)
        self.duration_spin.setValue(4500)
        self.duration_spin.setSuffix(" мс")
        form.addRow("Время кручения:", self.duration_spin)

        self.min_turns_spin = QSpinBox()
        self.min_turns_spin.setRange(1, 80)
        self.min_turns_spin.setValue(5)
        form.addRow("Минимум оборотов:", self.min_turns_spin)

        self.max_turns_spin = QSpinBox()
        self.max_turns_spin.setRange(1, 120)
        self.max_turns_spin.setValue(9)
        form.addRow("Максимум оборотов:", self.max_turns_spin)

        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 999_999_999)
        self.seed_spin.setValue(random.randint(1, 999_999))
        form.addRow("Random seed (0 = случайный):", self.seed_spin)

        self.remove_winner_box = QCheckBox("Удалять выпавший вариант из текущего колеса")
        form.addRow("Повторы:", self.remove_winner_box)
        layout.addLayout(form)

        self.stats_label = QLabel("Файл не загружен.")
        self.stats_label.setObjectName("StatsLabel")
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)

        self.issues_box = QTextEdit()
        self.issues_box.setReadOnly(True)
        self.issues_box.setPlaceholderText("Проблемы импорта будут показаны здесь.")
        self.issues_box.setMinimumHeight(140)
        layout.addWidget(self.issues_box)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("Открыть колесо")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_wheel)
        buttons.addStretch(1)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)

        self.setCentralWidget(root)

    def _refresh_autosave_button(self) -> None:
        self.continue_button.setEnabled(has_autosave())

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите словарик", "", "Text files (*.txt);;All files (*.*)")
        if not path:
            return
        result = parse_wheel_file(path)
        self.parse_result = result
        self.items = result.items
        stats = result.stats()
        self.stats_label.setText(
            f"Загружено: {Path(path).name}\n"
            f"Всего вариантов: {stats.get('Всего', 0)} | "
            f"Со значением: {stats.get('Со значением', 0)} | "
            f"Без значения: {stats.get('Без значения', 0)} | "
            f"Проблемы: {stats.get('Проблемы', 0)}"
        )
        if result.issues:
            self.issues_box.setPlainText("\n".join(f"Строка {i.line_number}: {i.message} | {i.text}" for i in result.issues[:200]))
        else:
            self.issues_box.setPlainText("Проблем импорта не найдено.")
        self.start_button.setEnabled(bool(self.items))
        if not self.items:
            QMessageBox.warning(self, "Импорт", "Не удалось разобрать ни одного варианта.")

    def _options(self) -> SpinOptions:
        min_turns = self.min_turns_spin.value()
        max_turns = self.max_turns_spin.value()
        if max_turns < min_turns:
            min_turns, max_turns = max_turns, min_turns
        return SpinOptions(
            mode=self.mode_combo.currentData(),
            spin_duration_ms=self.duration_spin.value(),
            min_turns=min_turns,
            max_turns=max_turns,
            remove_winner=self.remove_winner_box.isChecked(),
            random_seed=self.seed_spin.value(),
        )

    def start_wheel(self) -> None:
        if not self.items:
            return
        engine = WheelEngine.new(self.items, self._options())
        write_autosave(engine.session)
        self.wheel_window = WheelWindow(engine)
        self.wheel_window.show()
        self.close()

    def continue_autosave(self) -> None:
        try:
            session = read_autosave()
        except Exception as exc:
            QMessageBox.critical(self, "Autosave", f"Не удалось прочитать autosave:\n{exc}")
            self._refresh_autosave_button()
            return
        self.wheel_window = WheelWindow(WheelEngine(session))
        self.wheel_window.show()
        self.close()
