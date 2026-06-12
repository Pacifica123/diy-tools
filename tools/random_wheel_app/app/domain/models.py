from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


WheelMode = Literal["equal", "weighted"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class WheelItem:
    id: int
    label: str
    value: float | None = None
    source_line: int = 0

    def normalized_label(self) -> str:
        return " ".join(self.label.split())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "value": self.value,
            "source_line": self.source_line,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WheelItem":
        raw_value = data.get("value")
        return cls(
            id=int(data["id"]),
            label=str(data.get("label", "")),
            value=None if raw_value is None else float(raw_value),
            source_line=int(data.get("source_line", 0)),
        )


@dataclass
class SpinOptions:
    mode: WheelMode = "equal"
    spin_duration_ms: int = 4500
    min_turns: int = 5
    max_turns: int = 9
    remove_winner: bool = False
    random_seed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "spin_duration_ms": self.spin_duration_ms,
            "min_turns": self.min_turns,
            "max_turns": self.max_turns,
            "remove_winner": self.remove_winner,
            "random_seed": self.random_seed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpinOptions":
        return cls(
            mode=data.get("mode", "equal"),
            spin_duration_ms=int(data.get("spin_duration_ms", 4500)),
            min_turns=int(data.get("min_turns", 5)),
            max_turns=int(data.get("max_turns", 9)),
            remove_winner=bool(data.get("remove_winner", False)),
            random_seed=int(data.get("random_seed", 0)),
        )


@dataclass
class SpinRecord:
    item_id: int
    label: str
    mode: WheelMode
    effective_weight: float
    total_weight: float
    probability: float
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "mode": self.mode,
            "effective_weight": self.effective_weight,
            "total_weight": self.total_weight,
            "probability": self.probability,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpinRecord":
        return cls(
            item_id=int(data.get("item_id", 0)),
            label=str(data.get("label", "")),
            mode=data.get("mode", "equal"),
            effective_weight=float(data.get("effective_weight", 0)),
            total_weight=float(data.get("total_weight", 0)),
            probability=float(data.get("probability", 0)),
            created_at=str(data.get("created_at") or now_iso()),
        )


@dataclass
class WheelSession:
    items: list[WheelItem]
    active_ids: list[int]
    options: SpinOptions = field(default_factory=SpinOptions)
    history: list[SpinRecord] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "active_ids": list(self.active_ids),
            "options": self.options.to_dict(),
            "history": [record.to_dict() for record in self.history],
            "created_at": self.created_at,
            "updated_at": now_iso(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WheelSession":
        return cls(
            items=[WheelItem.from_dict(raw) for raw in data.get("items", [])],
            active_ids=[int(x) for x in data.get("active_ids", [])],
            options=SpinOptions.from_dict(data.get("options", {})),
            history=[SpinRecord.from_dict(raw) for raw in data.get("history", [])],
            created_at=str(data.get("created_at") or now_iso()),
            updated_at=str(data.get("updated_at") or now_iso()),
        )

    def active_items(self) -> list[WheelItem]:
        active = set(self.active_ids)
        return [item for item in self.items if item.id in active]

    def item_by_id(self, item_id: int) -> WheelItem:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(f"Unknown item id: {item_id}")
