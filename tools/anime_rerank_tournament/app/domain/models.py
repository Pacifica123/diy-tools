from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


ScoreMode = Literal["light", "hard"]
TournamentStatus = Literal["not_started", "in_progress", "finished"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class TitleItem:
    id: int
    source_index: int
    title: str
    old_score: float | None = None
    episodes: str = ""
    type: str = ""
    comment: str | None = None
    wins: int = 0
    losses: int = 0
    bye_count: int = 0
    eliminated_round: int | None = None
    lost_to_id: int | None = None
    new_score: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_index": self.source_index,
            "title": self.title,
            "old_score": self.old_score,
            "episodes": self.episodes,
            "type": self.type,
            "comment": self.comment,
            "wins": self.wins,
            "losses": self.losses,
            "bye_count": self.bye_count,
            "eliminated_round": self.eliminated_round,
            "lost_to_id": self.lost_to_id,
            "new_score": self.new_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TitleItem":
        return cls(
            id=int(data["id"]),
            source_index=int(data.get("source_index", data["id"])),
            title=str(data.get("title", "")),
            old_score=data.get("old_score"),
            episodes=str(data.get("episodes", "")),
            type=str(data.get("type", "")),
            comment=data.get("comment"),
            wins=int(data.get("wins", 0)),
            losses=int(data.get("losses", 0)),
            bye_count=int(data.get("bye_count", 0)),
            eliminated_round=data.get("eliminated_round"),
            lost_to_id=data.get("lost_to_id"),
            new_score=data.get("new_score"),
        )


@dataclass
class Match:
    id: str
    round_number: int
    left_id: int
    right_id: int | None
    winner_id: int | None = None
    loser_id: int | None = None
    is_bye: bool = False
    created_at: str = field(default_factory=now_iso)
    resolved_at: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.winner_id is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "round_number": self.round_number,
            "left_id": self.left_id,
            "right_id": self.right_id,
            "winner_id": self.winner_id,
            "loser_id": self.loser_id,
            "is_bye": self.is_bye,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Match":
        return cls(
            id=str(data["id"]),
            round_number=int(data["round_number"]),
            left_id=int(data["left_id"]),
            right_id=None if data.get("right_id") is None else int(data["right_id"]),
            winner_id=None if data.get("winner_id") is None else int(data["winner_id"]),
            loser_id=None if data.get("loser_id") is None else int(data["loser_id"]),
            is_bye=bool(data.get("is_bye", False)),
            created_at=str(data.get("created_at") or now_iso()),
            resolved_at=data.get("resolved_at"),
        )


@dataclass
class TournamentState:
    items: list[TitleItem]
    active_ids: list[int]
    eliminated_ids: list[int] = field(default_factory=list)
    round_winner_ids: list[int] = field(default_factory=list)
    round_number: int = 0
    current_matches: list[Match] = field(default_factory=list)
    completed_matches: list[Match] = field(default_factory=list)
    random_seed: int = 0
    mode: ScoreMode = "light"
    status: TournamentStatus = "not_started"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    undo_stack: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, include_undo: bool = True) -> dict[str, Any]:
        data = {
            "items": [item.to_dict() for item in self.items],
            "active_ids": self.active_ids,
            "eliminated_ids": self.eliminated_ids,
            "round_winner_ids": self.round_winner_ids,
            "round_number": self.round_number,
            "current_matches": [match.to_dict() for match in self.current_matches],
            "completed_matches": [match.to_dict() for match in self.completed_matches],
            "random_seed": self.random_seed,
            "mode": self.mode,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_undo:
            data["undo_stack"] = self.undo_stack
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TournamentState":
        return cls(
            items=[TitleItem.from_dict(raw) for raw in data.get("items", [])],
            active_ids=[int(x) for x in data.get("active_ids", [])],
            eliminated_ids=[int(x) for x in data.get("eliminated_ids", [])],
            round_winner_ids=[int(x) for x in data.get("round_winner_ids", [])],
            round_number=int(data.get("round_number", 0)),
            current_matches=[Match.from_dict(raw) for raw in data.get("current_matches", [])],
            completed_matches=[Match.from_dict(raw) for raw in data.get("completed_matches", [])],
            random_seed=int(data.get("random_seed", 0)),
            mode=data.get("mode", "light"),
            status=data.get("status", "not_started"),
            created_at=str(data.get("created_at") or now_iso()),
            updated_at=str(data.get("updated_at") or now_iso()),
            undo_stack=list(data.get("undo_stack", [])),
        )

    def item_by_id(self, item_id: int) -> TitleItem:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(f"Unknown item id: {item_id}")
