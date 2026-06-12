from __future__ import annotations

from pathlib import Path

from app.domain.models import TournamentState
from app.storage.save_load import load_state, save_state


APP_DIR_NAME = "anime_rerank_tournament"
AUTOSAVE_NAME = "autosave.json"


def autosave_dir() -> Path:
    return Path.home() / ".anime_rerank_tournament"


def autosave_path() -> Path:
    return autosave_dir() / AUTOSAVE_NAME


def has_autosave() -> bool:
    return autosave_path().exists()


def write_autosave(state: TournamentState) -> None:
    save_state(autosave_path(), state)


def read_autosave() -> TournamentState:
    return load_state(autosave_path())


def clear_autosave() -> None:
    path = autosave_path()
    if path.exists():
        path.unlink()
