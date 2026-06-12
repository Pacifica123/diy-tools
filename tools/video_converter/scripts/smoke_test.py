from __future__ import annotations

import json
import tempfile
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cli import main  # noqa: E402


def run() -> int:
    with tempfile.TemporaryDirectory(prefix="video_converter_smoke_") as tmp:
        base = Path(tmp)
        source = base / "тестовый файл.mkv"
        source.write_bytes(b"not a real video; dry-run only")
        report = base / "report.json"
        code = main([str(base), "--dry-run", "--report", str(report)])
        assert code == 0
        assert source.exists(), "dry-run must not delete source"
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["summary"]["found"] == 1
        assert data["summary"]["dry_run"] is True
        assert data["results"][0]["status"] == "planned"
    print("video_converter smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
