from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.domain.export import export_matches_json, export_ranking_csv, export_ranking_json, export_ranking_txt
from app.domain.models import TournamentState
from app.domain.ranking import RankedItem, build_ranking
from app.domain.scoring import apply_scores
from app.storage.autosave import write_autosave


class ResultWindow(QMainWindow):
    def __init__(self, state: TournamentState):
        super().__init__()
        self.state = state
        self.ranking: list[RankedItem] = apply_scores(build_ranking(state), state.mode)
        write_autosave(self.state)
        self.setWindowTitle("Итоговое ранжирование")
        self.resize(1220, 760)
        self._build_ui()
        self._fill_table()
        self._fill_distribution()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        title = QLabel("Итоговое ранжирование")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.distribution = QTextEdit()
        self.distribution.setReadOnly(True)
        self.distribution.setMaximumHeight(130)
        layout.addWidget(self.distribution)

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(
            ["Место", "Название", "Старая", "Новая", "Изм.", "Тип", "Эпизоды", "Раунд", "Проиграл", "Комментарий"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        for label, handler in (
            ("Экспорт TXT", self.export_txt),
            ("Экспорт CSV", self.export_csv),
            ("Экспорт JSON", self.export_json),
            ("История матчей JSON", self.export_matches),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.setCentralWidget(root)

    def _fill_distribution(self) -> None:
        counter = Counter(item.item.new_score for item in self.ranking)
        lines = ["Распределение новых оценок:"]
        for score in sorted(counter.keys(), reverse=True):
            count = counter[score]
            bar = "█" * min(60, count)
            lines.append(f"{score}: {count:>4} {bar}")
        self.distribution.setPlainText("\n".join(lines))

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self.ranking))
        for row, ranked in enumerate(self.ranking):
            item = ranked.item
            delta = ""
            if item.old_score is not None and item.new_score is not None:
                delta = f"{item.new_score - float(item.old_score):+g}"
            values = [
                ranked.rank,
                item.title,
                item.old_score if item.old_score is not None else "",
                item.new_score if item.new_score is not None else "",
                delta,
                item.type,
                item.episodes,
                item.eliminated_round if item.eliminated_round is not None else "Победитель",
                ranked.lost_to_title or "",
                item.comment or "",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if col in {0, 2, 3, 4, 7}:
                    cell.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, cell)
        self.table.resizeColumnsToContents()

    def _save_path(self, title: str, suffix: str, filters: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(self, title, f"ranking.{suffix}", filters)
        return path or None

    def export_txt(self) -> None:
        path = self._save_path("Экспорт TXT", "txt", "Text files (*.txt)")
        if path:
            export_ranking_txt(path, self.ranking)
            QMessageBox.information(self, "Экспорт", f"Сохранено: {Path(path).name}")

    def export_csv(self) -> None:
        path = self._save_path("Экспорт CSV", "csv", "CSV files (*.csv)")
        if path:
            export_ranking_csv(path, self.ranking)
            QMessageBox.information(self, "Экспорт", f"Сохранено: {Path(path).name}")

    def export_json(self) -> None:
        path = self._save_path("Экспорт JSON", "json", "JSON files (*.json)")
        if path:
            export_ranking_json(path, self.ranking)
            QMessageBox.information(self, "Экспорт", f"Сохранено: {Path(path).name}")

    def export_matches(self) -> None:
        path = self._save_path("Экспорт истории матчей", "json", "JSON files (*.json)")
        if path:
            export_matches_json(path, self.state.completed_matches)
            QMessageBox.information(self, "Экспорт", f"Сохранено: {Path(path).name}")
