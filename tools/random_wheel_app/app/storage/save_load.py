from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import WheelSession


def write_session(session: WheelSession, path: str | Path) -> None:
    Path(path).write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def read_session(path: str | Path) -> WheelSession:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return WheelSession.from_dict(data)
