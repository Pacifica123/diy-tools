from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.domain.tournament import TournamentEngine
from app.storage.autosave import write_autosave
from app.ui.result_window import ResultWindow
from app.ui.widgets import TitleCard


class TournamentWindow(QMainWindow):
    def __init__(self, engine: TournamentEngine):
        super().__init__()
        self.engine = engine
        self.result_window: ResultWindow | None = None
        self.setWindowTitle("Карточный турнир")
        self.resize(1180, 760)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        self.header = QLabel("")
        self.header.setObjectName("PageTitle")
        layout.addWidget(self.header)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        content = QHBoxLayout()
        cards = QHBoxLayout()
        self.left_card = TitleCard("Клавиша 1 / Левая карточка")
        self.right_card = TitleCard("Клавиша 2 / Правая карточка")
        self.left_card.clicked.connect(self.choose_left)
        self.right_card.clicked.connect(self.choose_right)
        cards.addWidget(self.left_card, 1)
        cards.addWidget(self.right_card, 1)
        content.addLayout(cards, 4)

        side = QVBoxLayout()
        side.addWidget(QLabel("Сетка"))
        self.bracket_box = QTextEdit()
        self.bracket_box.setReadOnly(True)
        self.bracket_box.setMaximumWidth(260)
        side.addWidget(self.bracket_box, 1)
        content.addLayout(side, 1)
        layout.addLayout(content, 1)

        buttons = QHBoxLayout()
        self.undo_button = QPushButton("Отменить последний выбор")
        self.undo_button.clicked.connect(self.undo)
        buttons.addWidget(self.undo_button)

        self.skip_button = QPushButton("Пропустить пару")
        self.skip_button.clicked.connect(self.skip)
        buttons.addWidget(self.skip_button)

        self.save_button = QPushButton("Сохранить")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)

        self.exit_button = QPushButton("Выйти")
        self.exit_button.clicked.connect(self.close)
        buttons.addWidget(self.exit_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.setCentralWidget(root)

    def keyPressEvent(self, event):  # noqa: N802 - Qt API name
        if event.key() == Qt.Key_1:
            self.choose_left()
        elif event.key() == Qt.Key_2:
            self.choose_right()
        else:
            super().keyPressEvent(event)

    def refresh(self) -> None:
        if self.engine.is_finished():
            self.open_results()
            return

        match = self.engine.current_match()
        if match is None:
            self.header.setText("Матч не найден. Попробуйте сохранить и перезапустить турнир.")
            return

        left = self.engine.get_item(match.left_id)
        right = self.engine.get_item(match.right_id) if match.right_id is not None else None
        if right is None:
            self.refresh()
            return

        current_no, total = self.engine.current_match_position()
        mode_label = "Хардовый" if self.engine.state.mode == "hard" else "Лайтовый"
        self.header.setText(
            f"Раунд {self.engine.state.round_number} из ~{self.engine.estimated_total_rounds()} | "
            f"Матч {current_no} из {total} | "
            f"Осталось участников: {len(self.engine.state.active_ids)} | "
            f"Режим: {mode_label}"
        )

        completed = self.engine.completed_user_match_count()
        total_required = self.engine.total_required_user_matches()
        self.progress.setMaximum(max(1, total_required))
        self.progress.setValue(min(completed, total_required))
        self.progress.setFormat(f"Выборов сделано: {completed}/{total_required}")

        self.left_card.set_item(left)
        self.right_card.set_item(right)
        self.undo_button.setEnabled(bool(self.engine.state.undo_stack))

        lines = []
        for line_no, line in enumerate(self.engine.round_plan_lines(), start=1):
            marker = "▶ " if line_no == self.engine.state.round_number else "  "
            lines.append(marker + line)
        self.bracket_box.setPlainText("\n".join(lines))

    def choose_left(self) -> None:
        try:
            self.engine.select_left()
            write_autosave(self.engine.state)
        except Exception as exc:
            QMessageBox.warning(self, "Выбор", str(exc))
        self.refresh()

    def choose_right(self) -> None:
        try:
            self.engine.select_right()
            write_autosave(self.engine.state)
        except Exception as exc:
            QMessageBox.warning(self, "Выбор", str(exc))
        self.refresh()

    def skip(self) -> None:
        self.engine.skip_current_match()
        write_autosave(self.engine.state)
        self.refresh()

    def undo(self) -> None:
        if self.engine.undo_last_action():
            write_autosave(self.engine.state)
            self.refresh()
        else:
            QMessageBox.information(self, "Отмена", "Нет действия для отмены.")

    def save(self) -> None:
        write_autosave(self.engine.state)
        QMessageBox.information(self, "Сохранение", "Турнир сохранён в autosave.")

    def open_results(self) -> None:
        write_autosave(self.engine.state)
        self.result_window = ResultWindow(self.engine.state)
        self.result_window.show()
        self.close()
