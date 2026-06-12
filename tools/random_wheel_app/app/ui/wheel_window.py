from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.domain.export import export_history_csv, export_history_json, export_history_txt
from app.domain.wheel import Segment, WheelEngine
from app.storage.autosave import write_autosave
from app.ui.wheel_widget import WheelWidget


class WheelWindow(QMainWindow):
    def __init__(self, engine: WheelEngine):
        super().__init__()
        self.engine = engine
        self.animation: QPropertyAnimation | None = None
        self.pending_selection = None
        self.setWindowTitle("Колесо рандома")
        self.resize(1180, 760)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)

        left = QVBoxLayout()
        self.header = QLabel("")
        self.header.setObjectName("PageTitle")
        left.addWidget(self.header)

        self.wheel = WheelWidget()
        left.addWidget(self.wheel, 1)

        buttons = QHBoxLayout()
        self.spin_button = QPushButton("Крутить")
        self.spin_button.clicked.connect(self.spin)
        buttons.addWidget(self.spin_button)

        self.reset_button = QPushButton("Вернуть все варианты")
        self.reset_button.clicked.connect(self.reset_active)
        buttons.addWidget(self.reset_button)

        self.save_button = QPushButton("Сохранить")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)
        left.addLayout(buttons)

        layout.addLayout(left, 3)

        side = QVBoxLayout()
        self.result_label = QLabel("Результат: -")
        self.result_label.setObjectName("ResultLabel")
        self.result_label.setWordWrap(True)
        side.addWidget(self.result_label)

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("StatsLabel")
        self.stats_label.setWordWrap(True)
        side.addWidget(self.stats_label)

        side.addWidget(QLabel("История"))
        self.history_box = QTextEdit()
        self.history_box.setReadOnly(True)
        side.addWidget(self.history_box, 1)

        self.export_button = QPushButton("Экспорт истории")
        self.export_button.clicked.connect(self.export_history)
        side.addWidget(self.export_button)

        self.clear_history_button = QPushButton("Очистить историю")
        self.clear_history_button.clicked.connect(self.clear_history)
        side.addWidget(self.clear_history_button)

        layout.addLayout(side, 1)
        self.setCentralWidget(root)

    def refresh(self) -> None:
        segments = self.engine.segments()
        self.wheel.set_segments(segments)

        mode_label = "со значением" if self.engine.session.options.mode == "weighted" else "без значения"
        self.header.setText(f"Режим: {mode_label}")
        active_count = len(self.engine.active_items())
        total_count = len(self.engine.session.items)
        total_weight = self.engine.total_weight()
        remove_label = "да" if self.engine.session.options.remove_winner else "нет"
        self.stats_label.setText(
            f"Активно: {active_count}/{total_count}\n"
            f"Суммарный вес: {total_weight:g}\n"
            f"Время кручения: {self.engine.session.options.spin_duration_ms} мс\n"
            f"Обороты: {self.engine.session.options.min_turns}-{self.engine.session.options.max_turns}\n"
            f"Удалять выпавший вариант: {remove_label}"
        )
        self.spin_button.setEnabled(active_count > 0 and self.animation is None)
        self.reset_button.setEnabled(active_count < total_count)
        self.export_button.setEnabled(bool(self.engine.session.history))
        self.clear_history_button.setEnabled(bool(self.engine.session.history))
        self.history_box.setPlainText(self._history_text())

    def _history_text(self) -> str:
        lines = []
        for idx, record in enumerate(self.engine.session.history, start=1):
            lines.append(
                f"{idx}. {record.label}\n"
                f"   шанс: {record.probability * 100:.2f}% | вес: {record.effective_weight:g} | {record.created_at}"
            )
        return "\n".join(lines) if lines else "Пока пусто."

    def spin(self) -> None:
        if self.animation is not None:
            return
        try:
            item, weight, total = self.engine.select_item()
        except Exception as exc:
            QMessageBox.warning(self, "Колесо", str(exc))
            return

        segments = self.engine.segments()
        selected_segment = next((s for s in segments if s.item.id == item.id), None)
        if selected_segment is None:
            QMessageBox.warning(self, "Колесо", "Не удалось найти выбранный сегмент.")
            return

        self.pending_selection = (item, weight, total)
        target_rotation = self._target_rotation_for_segment(selected_segment)

        self.spin_button.setEnabled(False)
        self.animation = QPropertyAnimation(self.wheel, b"wheelRotation")
        self.animation.setStartValue(self.wheel.current_rotation())
        self.animation.setEndValue(target_rotation)
        self.animation.setDuration(self.engine.session.options.spin_duration_ms)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.finished.connect(self.finish_spin)
        self.animation.start()

    def _target_rotation_for_segment(self, segment: Segment) -> float:
        span = segment.span
        if span <= 0:
            target_angle = segment.middle_angle
        else:
            safe_margin = min(span * 0.22, 10.0)
            if span <= safe_margin * 2:
                target_angle = segment.middle_angle
            else:
                target_angle = self.engine.random.uniform(segment.start_angle + safe_margin, segment.end_angle - safe_margin)

        current = self.wheel.current_rotation()
        target_mod = (-target_angle) % 360.0
        current_mod = current % 360.0
        delta = (target_mod - current_mod) % 360.0
        turns = self.engine.random.randint(self.engine.session.options.min_turns, self.engine.session.options.max_turns)
        return current + delta + turns * 360.0

    def finish_spin(self) -> None:
        if self.pending_selection is None:
            self.animation = None
            self.refresh()
            return

        item, weight, total = self.pending_selection
        record = self.engine.record_spin(item, weight, total)
        self.result_label.setText(
            f"Результат: {record.label}\n"
            f"Шанс на момент кручения: {record.probability * 100:.2f}%"
        )
        write_autosave(self.engine.session)
        self.pending_selection = None
        self.animation = None
        self.refresh()

    def reset_active(self) -> None:
        self.engine.reset_active()
        write_autosave(self.engine.session)
        self.refresh()

    def clear_history(self) -> None:
        self.engine.clear_history()
        write_autosave(self.engine.session)
        self.result_label.setText("Результат: -")
        self.refresh()

    def save(self) -> None:
        write_autosave(self.engine.session)
        QMessageBox.information(self, "Сохранение", "Сессия сохранена в autosave.")

    def export_history(self) -> None:
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Экспорт истории",
            "wheel_history.csv",
            "CSV (*.csv);;JSON (*.json);;Text (*.txt)",
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        try:
            if suffix == ".json" or "JSON" in selected_filter:
                export_history_json(self.engine.session.history, path)
            elif suffix == ".txt" or "Text" in selected_filter:
                export_history_txt(self.engine.session.history, path)
            else:
                export_history_csv(self.engine.session.history, path)
        except Exception as exc:
            QMessageBox.critical(self, "Экспорт", f"Не удалось экспортировать историю:\n{exc}")
            return
        QMessageBox.information(self, "Экспорт", "История экспортирована.")
