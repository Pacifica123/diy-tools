from __future__ import annotations

from pathlib import Path

from app.domain.models import WheelSession
from app.storage.save_load import read_session, write_session

AUTOSAVE_PATH = Path.home() / ".random_wheel_app_autosave.json"


def has_autosave() -> bool:
    return AUTOSAVE_PATH.exists()


def write_autosave(session: WheelSession) -> None:
    write_session(session, AUTOSAVE_PATH)


def read_autosave() -> WheelSession:
    return read_session(AUTOSAVE_PATH)
