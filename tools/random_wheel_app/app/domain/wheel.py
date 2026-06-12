from __future__ import annotations

from dataclasses import dataclass
import random

from app.domain.models import SpinOptions, SpinRecord, WheelItem, WheelMode, WheelSession, now_iso


@dataclass(frozen=True)
class Segment:
    item: WheelItem
    start_angle: float
    end_angle: float
    weight: float
    probability: float

    @property
    def span(self) -> float:
        return self.end_angle - self.start_angle

    @property
    def middle_angle(self) -> float:
        return self.start_angle + self.span / 2


class WheelEngine:
    def __init__(self, session: WheelSession):
        self.session = session
        seed = session.options.random_seed
        self.random = random.Random(seed if seed else None)

    @classmethod
    def new(cls, items: list[WheelItem], options: SpinOptions) -> "WheelEngine":
        session = WheelSession(items=items, active_ids=[item.id for item in items], options=options)
        return cls(session)

    def active_items(self) -> list[WheelItem]:
        return self.session.active_items()

    def effective_weight(self, item: WheelItem, mode: WheelMode | None = None) -> float:
        mode = mode or self.session.options.mode
        if mode == "equal":
            return 1.0
        if item.value is None or item.value <= 0:
            return 1.0
        return float(item.value)

    def total_weight(self) -> float:
        return sum(self.effective_weight(item) for item in self.active_items())

    def segments(self) -> list[Segment]:
        active = self.active_items()
        total = sum(self.effective_weight(item) for item in active)
        if not active or total <= 0:
            return []

        result: list[Segment] = []
        angle = 0.0
        for index, item in enumerate(active):
            weight = self.effective_weight(item)
            if index == len(active) - 1:
                end = 360.0
            else:
                end = angle + 360.0 * weight / total
            result.append(Segment(item=item, start_angle=angle, end_angle=end, weight=weight, probability=weight / total))
            angle = end
        return result

    def select_item(self) -> tuple[WheelItem, float, float]:
        active = self.active_items()
        if not active:
            raise ValueError("Нет активных вариантов.")
        weights = [self.effective_weight(item) for item in active]
        total = sum(weights)
        if total <= 0:
            raise ValueError("Суммарный вес должен быть больше нуля.")
        selected = self.random.choices(active, weights=weights, k=1)[0]
        selected_weight = self.effective_weight(selected)
        return selected, selected_weight, total

    def record_spin(self, item: WheelItem, weight: float, total: float) -> SpinRecord:
        record = SpinRecord(
            item_id=item.id,
            label=item.label,
            mode=self.session.options.mode,
            effective_weight=weight,
            total_weight=total,
            probability=weight / total if total else 0,
        )
        self.session.history.append(record)
        if self.session.options.remove_winner and item.id in self.session.active_ids:
            self.session.active_ids.remove(item.id)
        self.session.updated_at = now_iso()
        return record

    def reset_active(self) -> None:
        self.session.active_ids = [item.id for item in self.session.items]
        self.session.updated_at = now_iso()

    def clear_history(self) -> None:
        self.session.history = []
        self.session.updated_at = now_iso()
