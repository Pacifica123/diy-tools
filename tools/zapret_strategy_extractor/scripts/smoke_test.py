from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sample_orchestra.log"


def main() -> int:
    assert SAMPLE.is_file(), SAMPLE
    cargo = shutil.which("cargo")
    if cargo is None:
        source = (ROOT / "src" / "main.rs").read_text(encoding="utf-8")
        assert "best-effort" in source
        assert "write_events_tsv" in source
        assert "progress_lines" in source
        print("cargo not found: source-level smoke passed, build smoke skipped")
        return 0

    preset = ROOT / "examples" / "smoke_preset.txt"
    stats = ROOT / "examples" / "smoke_stats.json"
    events = ROOT / "examples" / "smoke_events.tsv"
    for path in (preset, stats, events):
        if path.exists():
            path.unlink()
    cmd = [
        cargo, "run", "--quiet", "--", str(SAMPLE),
        "--preset-out", str(preset),
        "--stats-out", str(stats),
        "--events-out", str(events),
        "--progress-lines", "0",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    assert preset.is_file(), preset
    assert stats.is_file(), stats
    assert events.is_file(), events
    data = json.loads(stats.read_text(encoding="utf-8"))
    assert "notes" in data and data["notes"]
    for path in (preset, stats, events):
        path.unlink()
    print("zapret_strategy_extractor smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
