from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    devctl = ROOT / "devctl.py"
    assert devctl.is_file(), devctl
    result = subprocess.run([sys.executable, str(devctl), "--version"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr
    assert "devctl" in result.stdout.lower(), result.stdout
    assert (ROOT / "gui" / "devctl_gui.py").is_file()
    assert (ROOT / "docs" / "patch-manifest.example.json").is_file()
    print(result.stdout.strip())
    print("devctl_universal smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
