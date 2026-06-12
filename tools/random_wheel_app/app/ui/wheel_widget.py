from __future__ import annotations

import math

from PySide6.QtCore import Property, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.domain.wheel import Segment


class WheelWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._rotation = 0.0
        self._segments: list[Segment] = []
        self.setMinimumSize(520, 520)
        self.colors = [
            QColor("#5470c6"),
            QColor("#91cc75"),
            QColor("#fac858"),
            QColor("#ee6666"),
            QColor("#73c0de"),
            QColor("#3ba272"),
            QColor("#fc8452"),
            QColor("#9a60b4"),
            QColor("#ea7ccc"),
            QColor("#6e7f9e"),
        ]

    def rotation(self) -> float:
        return self._rotation

    def setRotation(self, value: float) -> None:  # noqa: N802 - Qt property naming
        self._rotation = float(value)
        self.update()

    wheelRotation = Property(float, rotation, setRotation)

    def set_segments(self, segments: list[Segment]) -> None:
        self._segments = segments
        self.update()

    def current_rotation(self) -> float:
        return self._rotation

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        side = min(self.width(), self.height()) - 34
        rect = QRectF(-side / 2, -side / 2, side, side)
        center = QPointF(self.width() / 2, self.height() / 2 + 8)

        painter.translate(center)
        self._draw_shadow(painter, rect)

        if not self._segments:
            self._draw_empty(painter, rect)
            painter.resetTransform()
            self._draw_pointer(painter)
            return

        painter.save()
        painter.rotate(self._rotation)
        for index, segment in enumerate(self._segments):
            self._draw_segment(painter, rect, segment, self.colors[index % len(self.colors)])
        self._draw_center(painter)
        painter.restore()

        painter.resetTransform()
        self._draw_pointer(painter)

    def _draw_shadow(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(rect.adjusted(8, 10, 8, 10))
        painter.restore()

    def _draw_empty(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setBrush(QColor("#20283a"))
        painter.setPen(QPen(QColor("#3b4763"), 2))
        painter.drawEllipse(rect)
        painter.setPen(QColor("#dbe4ff"))
        font = painter.font()
        font.setPointSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, "Нет вариантов")
        painter.restore()

    def _draw_segment(self, painter: QPainter, rect: QRectF, segment: Segment, color: QColor) -> None:
        path = QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(self._point_on_circle(rect.width() / 2, segment.start_angle))
        path.arcTo(rect, 90 - segment.start_angle, -segment.span)
        path.closeSubpath()

        painter.save()
        painter.setBrush(color)
        painter.setPen(QPen(QColor("#151923"), 2))
        painter.drawPath(path)
        painter.restore()

        self._draw_segment_text(painter, rect, segment)

    def _draw_segment_text(self, painter: QPainter, rect: QRectF, segment: Segment) -> None:
        if segment.span < 8:
            return
        radius = rect.width() / 2
        label = segment.item.label.strip()
        if len(label) > 38:
            label = label[:35] + "..."
        if segment.item.value is not None and segment.span >= 16:
            label = f"{label} ({segment.item.value:g})"

        painter.save()
        painter.rotate(segment.middle_angle)
        painter.translate(0, -radius * 0.62)
        painter.rotate(0)
        text_rect = QRectF(-radius * 0.33, -18, radius * 0.66, 36)
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPointSize(9 if segment.span < 18 else 10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, label)
        painter.restore()

    def _draw_center(self, painter: QPainter) -> None:
        painter.save()
        painter.setBrush(QColor("#151923"))
        painter.setPen(QPen(QColor("#dbe4ff"), 2))
        painter.drawEllipse(QPointF(0, 0), 42, 42)
        painter.setPen(QColor("#dbe4ff"))
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(-38, -12, 76, 24), Qt.AlignCenter, "SPIN")
        painter.restore()

    def _draw_pointer(self, painter: QPainter) -> None:
        painter.save()
        x = self.width() / 2
        y = 12
        path = QPainterPath()
        path.moveTo(x, y + 48)
        path.lineTo(x - 18, y)
        path.lineTo(x + 18, y)
        path.closeSubpath()
        painter.setBrush(QColor("#f2f4f8"))
        painter.setPen(QPen(QColor("#151923"), 2))
        painter.drawPath(path)
        painter.restore()

    def _point_on_circle(self, radius: float, angle_deg: float) -> QPointF:
        radians = math.radians(angle_deg)
        return QPointF(math.sin(radians) * radius, -math.cos(radians) * radius)
