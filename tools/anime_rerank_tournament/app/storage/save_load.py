from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import TournamentState


def save_state(path: str | Path, state: TournamentState) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state.to_dict(include_undo=True), ensure_ascii=False, indent=2), encoding="utf-8")


def load_state(path: str | Path) -> TournamentState:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return TournamentState.from_dict(data)
