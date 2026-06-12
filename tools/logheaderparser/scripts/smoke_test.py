from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sample.log"


def main() -> int:
    assert SAMPLE.is_file(), SAMPLE
    cargo = shutil.which("cargo")
    if cargo is None:
        main_rs = ROOT / "src" / "main.rs"
        cargo_toml = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
        source = main_rs.read_text(encoding="utf-8")
        assert "BufReader" in source
        assert "progress_lines" in source
        assert 'version = "*"' not in cargo_toml
        print("cargo not found: source-level smoke passed, build smoke skipped")
        return 0

    out = ROOT / "examples" / "smoke_report.json"
    if out.exists():
        out.unlink()
    cmd = [cargo, "run", "--quiet", "--", str(SAMPLE), "--json", str(out), "--progress-lines", "0", "--top", "3"]
    subprocess.run(cmd, cwd=ROOT, check=True)
    assert out.is_file(), out
    text = out.read_text(encoding="utf-8")
    assert "unique_patterns" in text
    out.unlink()
    print("logheaderparser smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
