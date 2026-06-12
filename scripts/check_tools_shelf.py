from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
EXPECTED = {
    "devctl_universal",
    "random_wheel_app",
    "anime_rerank_tournament",
    "logheaderparser",
    "zapret_strategy_extractor",
    "video_converter",
    "react_app_launcher",
}
BANNED_PARTS = {".git", ".devctl", "node_modules", "target", "dist", "coverage", "__pycache__"}
BANNED_SUFFIXES = {".pyc", ".pyo"}
PERSONAL_PATH_PATTERNS = [
    re.compile(r"C:\\\\Users\\\\Noir", re.IGNORECASE),
    re.compile(r"/home/[^/\s]+/(Desktop|Documents|Downloads)/", re.IGNORECASE),
]


def fail(message: str) -> None:
    raise SystemExit(f"check_tools_shelf failed: {message}")


def parse_tool_ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    if not cp.has_section("tool"):
        fail(f"missing [tool] in {path}")
    return cp


def iter_patch_owned_paths():
    """Yield paths owned by this shelf patch, not the host repository metadata.

    The check may run inside a real git checkout, so scanning ROOT.rglob("*")
    would incorrectly fail on the existing project/.git directory.
    """
    roots = [TOOLS, ROOT / "TOOLS.md", ROOT / "scripts" / "check_tools_shelf.py"]
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            yield root
            continue
        for path in root.rglob("*"):
            yield path


def check_banned_payload() -> None:
    for path in iter_patch_owned_paths():
        rel = path.relative_to(ROOT)
        if any(part in BANNED_PARTS for part in rel.parts):
            fail(f"banned path in payload: {rel.as_posix()}")
        if path.suffix in BANNED_SUFFIXES:
            fail(f"banned bytecode in payload: {rel.as_posix()}")


def check_personal_paths() -> None:
    for path in TOOLS.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".ico", ".png", ".jpg", ".jpeg"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in PERSONAL_PATH_PATTERNS:
            if pattern.search(text):
                fail(f"personal absolute path found in {path.relative_to(ROOT).as_posix()}")


def check_capsules() -> None:
    if not TOOLS.is_dir():
        fail("tools/ directory missing")
    ids = {p.name for p in TOOLS.iterdir() if p.is_dir() and p.name != "__pycache__"}
    missing = EXPECTED - ids
    extra = ids - EXPECTED
    if missing:
        fail(f"missing tool capsules: {sorted(missing)}")
    if extra:
        fail(f"unexpected tool capsules: {sorted(extra)}")

    for tool_id in sorted(EXPECTED):
        capsule = TOOLS / tool_id
        readme = capsule / "README.md"
        ini = capsule / "tool.ini"
        if not readme.is_file():
            fail(f"{tool_id}: README.md missing")
        if not ini.is_file():
            fail(f"{tool_id}: tool.ini missing")
        cp = parse_tool_ini(ini)
        if cp.get("tool", "id", fallback="") != tool_id:
            fail(f"{tool_id}: tool.ini id mismatch")
        maturity = cp.get("tool", "maturity", fallback="")
        if maturity not in {"M1", "M2", "M3", "M4"}:
            fail(f"{tool_id}: invalid maturity {maturity}")
        flags = {x.strip() for x in cp.get("tool", "flags", fallback="none").split(",") if x.strip() and x.strip() != "none"}
        dangerous = cp.getboolean("safety", "dangerous", fallback=False)
        if "D" in flags and not dangerous:
            fail(f"{tool_id}: D flag requires safety.dangerous=true")
        if "D" not in flags and dangerous:
            fail(f"{tool_id}: dangerous=true without D flag")
        for key in ["network", "overwrites_files", "deletes_files", "runs_external_commands", "handles_private_files"]:
            if not cp.has_option("safety", key):
                fail(f"{tool_id}: safety.{key} missing")


def check_rust_cargo_toml() -> None:
    for cargo in TOOLS.glob("*/Cargo.toml"):
        text = cargo.read_text(encoding="utf-8")
        if 'version = "*"' in text or "= \"*\"" in text:
            fail(f"wildcard dependency in {cargo.relative_to(ROOT).as_posix()}")


def check_node_package() -> None:
    pkg_path = TOOLS / "react_app_launcher" / "package.json"
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for name, version in (pkg.get(section) or {}).items():
            if version in {"latest", "*"}:
                fail(f"{section}.{name} uses {version}")


def run_python_smoke(tool_id: str) -> None:
    script = TOOLS / tool_id / "scripts" / "smoke_test.py"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, str(script)], cwd=TOOLS / tool_id, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        fail(f"{tool_id}: smoke failed")
    print(result.stdout.strip())


def run_smokes() -> None:
    for tool_id in ["random_wheel_app", "anime_rerank_tournament", "video_converter", "devctl_universal", "logheaderparser", "zapret_strategy_extractor"]:
        run_python_smoke(tool_id)
    node = shutil.which("node")
    if node:
        script = TOOLS / "react_app_launcher" / "scripts" / "smoke_test.js"
        result = subprocess.run([node, str(script)], cwd=TOOLS / "react_app_launcher", text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            fail("react_app_launcher: node smoke failed")
        print(result.stdout.strip())
    else:
        print("node not found: react_app_launcher JS smoke skipped after package.json static check")


def main() -> int:
    if not (ROOT / "TOOLS.md").is_file():
        fail("TOOLS.md missing")
    check_capsules()
    check_banned_payload()
    check_personal_paths()
    check_rust_cargo_toml()
    check_node_package()
    run_smokes()
    print("check_tools_shelf passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
