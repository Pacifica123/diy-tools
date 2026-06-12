from __future__ import annotations

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout
except Exception:  # pragma: no cover - GUI dependency is optional for domain tests.
    Qt = None  # type: ignore
    Signal = object  # type: ignore
    QFrame = object  # type: ignore
    QLabel = object  # type: ignore
    QVBoxLayout = object  # type: ignore

from app.domain.models import TitleItem


class TitleCard(QFrame):
    clicked = Signal()

    def __init__(self, side_label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleCard")
        self.setCursor(Qt.PointingHandCursor)
        self.side = QLabel(side_label)
        self.side.setObjectName("CardSide")
        self.title = QLabel("")
        self.title.setObjectName("CardTitle")
        self.title.setWordWrap(True)
        self.meta = QLabel("")
        self.meta.setObjectName("CardMeta")
        self.meta.setWordWrap(True)
        self.comment = QLabel("")
        self.comment.setObjectName("CardComment")
        self.comment.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.side)
        layout.addWidget(self.title)
        layout.addWidget(self.meta)
        layout.addStretch(1)
        layout.addWidget(self.comment)

    def set_item(self, item: TitleItem) -> None:
        self.title.setText(item.title)
        score = "—" if item.old_score is None else str(item.old_score)
        self.meta.setText(f"Старая оценка: {score}\nЭпизоды: {item.episodes or '—'}\nТип: {item.type or '—'}")
        self.comment.setText(f"Комментарий:\n{item.comment}" if item.comment else "")

    def mousePressEvent(self, event):  # noqa: N802 - Qt API name
        self.clicked.emit()
        super().mousePressEvent(event)
