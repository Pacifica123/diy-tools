from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

from app.domain.models import TitleItem
from app.domain.parser import ParseResult, parse_title_file
from app.domain.tournament import TournamentEngine
from app.storage.autosave import has_autosave, read_autosave, write_autosave
from app.ui.tournament_window import TournamentWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Турнирная переоценка тайтлов")
        self.resize(940, 680)
        self.items: list[TitleItem] = []
        self.parse_result: ParseResult | None = None
        self.tournament_window: TournamentWindow | None = None
        self._build_ui()
        self._refresh_autosave_button()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        title = QLabel("Турнирная переоценка просмотренных тайтлов")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "Загрузите текстовый список, выберите режим оценивания и пройдите карточные сравнения."
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
        self.mode_combo.addItem("Лайтовый", "light")
        self.mode_combo.addItem("Хардовый", "hard")
        form.addRow("Режим:", self.mode_combo)

        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 999_999_999)
        self.seed_spin.setValue(random.randint(1, 999_999))
        form.addRow("Random seed:", self.seed_spin)
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

        self.start_button = QPushButton("Начать турнир")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_tournament)
        layout.addWidget(self.start_button, alignment=Qt.AlignRight)

        self.setCentralWidget(root)

    def _refresh_autosave_button(self) -> None:
        self.continue_button.setEnabled(has_autosave())

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите список", "", "Text files (*.txt);;All files (*.*)")
        if not path:
            return
        result = parse_title_file(path)
        self.parse_result = result
        self.items = result.items
        stats = result.stats()
        self.stats_label.setText(
            f"Загружено: {Path(path).name}\n"
            f"Всего тайтлов: {stats.get('Всего', 0)} | "
            f"Сериалов: {stats.get('Сериал', 0)} | "
            f"Фильмов: {stats.get('Фильм', 0)} | "
            f"OVA: {stats.get('OVA', 0)} | "
            f"Эпизодов: {stats.get('Эпизоды', 0)}"
        )
        if result.issues:
            self.issues_box.setPlainText(
                "\n".join(f"Строка {i.line_number}: {i.message} | {i.text}" for i in result.issues[:200])
            )
        else:
            self.issues_box.setPlainText("Проблем импорта не найдено.")
        self.start_button.setEnabled(bool(self.items))
        if not self.items:
            QMessageBox.warning(self, "Импорт", "Не удалось разобрать ни одной записи.")

    def start_tournament(self) -> None:
        if not self.items:
            return
        mode = self.mode_combo.currentData()
        engine = TournamentEngine.new(self.items, mode=mode, random_seed=self.seed_spin.value())
        write_autosave(engine.state)
        self.tournament_window = TournamentWindow(engine)
        self.tournament_window.show()
        self.close()

    def continue_autosave(self) -> None:
        try:
            state = read_autosave()
        except Exception as exc:
            QMessageBox.critical(self, "Autosave", f"Не удалось прочитать autosave:\n{exc}")
            self._refresh_autosave_button()
            return
        engine = TournamentEngine.from_state(state)
        self.tournament_window = TournamentWindow(engine)
        self.tournament_window.show()
        self.close()
