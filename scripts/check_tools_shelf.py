"""Проверка общей полки DIY-инструментов.

Сверяет реестр TOOLS.md с паспортами капсул, требует для M3 файлы из §4.1 стандарта,
запускает smoke-тесты всех капсул и убеждается, что они не оставили следов.

    python scripts/check_tools_shelf.py            # всё
    python scripts/check_tools_shelf.py --static   # без запуска smoke-тестов
"""
from __future__ import annotations

import configparser
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
REGISTRY = ROOT / "TOOLS.md"
STANDARD_VERSION = "0.2-devctl"

BANNED_PARTS = {".git", ".devctl", "node_modules", "target", "dist", "coverage", "__pycache__"}
BANNED_SUFFIXES = {".pyc", ".pyo"}
MATURITIES = ("M1", "M2", "M3", "M4")
STATUSES = {"draft", "working", "tested", "stable", "broken", "deprecated"}
SUPPORT_VALUES = {"tested", "expected", "unknown", "unsupported"}
SAFETY_KEYS = ("network", "overwrites_files", "deletes_files", "runs_external_commands", "handles_private_files")
REGISTRY_COLUMNS = (
    "ID", "Название", "Версия", "Статус", "Категория", "Зрелость", "Флаги", "Интерфейсы", "Среды", "Сеть", "Опасность",
    "Где лежит", "Проверка",
)
PERSONAL_PATH_PATTERNS = [
    re.compile(r"C:\\\\Users\\\\Noir", re.IGNORECASE),
    re.compile(r"/home/[^/\s]+/(Desktop|Documents|Downloads)/", re.IGNORECASE),
]
SKIP_MARKERS = ("пропущен", "не провер", "не запуск", "skipped")


def fail(message: str) -> None:
    raise SystemExit(f"check_tools_shelf failed: {message}")


def read_passport(tool_id: str) -> configparser.ConfigParser:
    path = TOOLS / tool_id / "tool.ini"
    if not path.is_file():
        fail(f"{tool_id}: tool.ini missing")
    passport = configparser.ConfigParser()
    passport.read(path, encoding="utf-8")
    if not passport.has_section("tool"):
        fail(f"{tool_id}: missing [tool] in tool.ini")
    return passport


def parse_flags(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip() and item.strip() != "none"}


def read_registry() -> dict[str, dict[str, str]]:
    """Строки таблицы TOOLS.md: id -> {колонка: значение}."""
    if not REGISTRY.is_file():
        fail("TOOLS.md missing")
    rows: dict[str, dict[str, str]] = {}
    header: list[str] | None = None
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            if header is not None and rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            if tuple(header) != REGISTRY_COLUMNS:
                fail(f"TOOLS.md: колонки таблицы должны быть {' | '.join(REGISTRY_COLUMNS)}")
            continue
        if set(cells[0]) <= {"-", ":"}:
            continue
        if len(cells) != len(header):
            fail(f"TOOLS.md: в строке {cells[0]!r} {len(cells)} ячеек вместо {len(header)}")
        if cells[0] in rows:
            fail(f"TOOLS.md: {cells[0]} записан дважды")
        rows[cells[0]] = dict(zip(header, cells))
    if not rows:
        fail("TOOLS.md: таблица реестра пуста")
    return rows


def capsule_ids() -> list[str]:
    if not TOOLS.is_dir():
        fail("tools/ directory missing")
    return sorted(path.name for path in TOOLS.iterdir() if path.is_dir() and path.name not in BANNED_PARTS)


def iter_shelf_files():
    """Файлы полки без каталогов сборки и кэшей: локальный target/ или node_modules — не часть полки."""
    for root in (TOOLS, ROOT / "scripts", ROOT / "docs"):
        if not root.is_dir():
            continue
        for current, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(name for name in dirnames if name not in BANNED_PARTS)
            for filename in sorted(filenames):
                yield Path(current) / filename
    for name in ("TOOLS.md", "README.md"):
        if (ROOT / name).is_file():
            yield ROOT / name


def shelf_listing() -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(ROOT).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in iter_shelf_files()
    }


def check_payload() -> None:
    for path in iter_shelf_files():
        rel = path.relative_to(ROOT)
        if path.suffix in BANNED_SUFFIXES:
            fail(f"banned bytecode in payload: {rel.as_posix()}")
        if path.suffix.lower() in {".ico", ".png", ".jpg", ".jpeg"} or rel.parts[0] == "docs":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in PERSONAL_PATH_PATTERNS:
            if pattern.search(text):
                fail(f"personal absolute path found in {rel.as_posix()}")


def check_capsule(tool_id: str, row: dict[str, str]) -> dict[str, str]:
    capsule = TOOLS / tool_id
    passport = read_passport(tool_id)
    get = lambda section, key: passport.get(section, key, fallback="").strip()  # noqa: E731

    readme = capsule / "README.md"
    if not readme.is_file():
        fail(f"{tool_id}: README.md missing")
    if get("tool", "id") != tool_id:
        fail(f"{tool_id}: tool.ini id mismatch")
    maturity, status, version = get("tool", "maturity"), get("tool", "status"), get("tool", "version")
    if maturity not in MATURITIES:
        fail(f"{tool_id}: invalid maturity {maturity!r}")
    if status not in STATUSES:
        fail(f"{tool_id}: invalid status {status!r}; допустимы {sorted(STATUSES)}")
    if not version:
        fail(f"{tool_id}: tool.ini version missing")
    if get("philosophy", "standard_version") != STANDARD_VERSION:
        fail(f"{tool_id}: standard_version должен быть {STANDARD_VERSION}")

    flags = parse_flags(get("tool", "flags") or "none")
    dangerous = passport.getboolean("safety", "dangerous", fallback=False)
    if "D" in flags and not dangerous:
        fail(f"{tool_id}: D flag requires safety.dangerous=true")
    if "D" not in flags and dangerous:
        fail(f"{tool_id}: dangerous=true without D flag")
    for key in SAFETY_KEYS:
        if not passport.has_option("safety", key):
            fail(f"{tool_id}: safety.{key} missing")
    for platform in ("windows", "linux"):
        if get("support", platform) not in SUPPORT_VALUES:
            fail(f"{tool_id}: support.{platform} должен быть одним из {sorted(SUPPORT_VALUES)}")

    # Реестр не должен расходиться с паспортом.
    expected_row = {
        "Версия": version, "Статус": status, "Зрелость": maturity, "Где лежит": f"tools/{tool_id}",
        "Проверка": get("checks", "smoke"), "Категория": get("tool", "category"), "Название": get("tool", "name_ru"),
    }
    for column, expected in expected_row.items():
        if row[column] != expected:
            fail(f"{tool_id}: TOOLS.md «{column}» = {row[column]!r}, а в tool.ini {expected!r}")
    if parse_flags(row["Флаги"]) != flags:
        fail(f"{tool_id}: флаги в TOOLS.md ({row['Флаги']}) не совпадают с tool.ini ({get('tool', 'flags')})")
    if (row["Опасность"] == "yes") != dangerous:
        fail(f"{tool_id}: «Опасность» в TOOLS.md не совпадает с safety.dangerous")

    readme_text = readme.read_text(encoding="utf-8")
    for label, value in (("Статус", status), ("Зрелость", maturity)):
        if f"{label}: `{value}`" not in readme_text:
            fail(f"{tool_id}: в README нет строки «{label}: `{value}`»")

    if MATURITIES.index(maturity) >= MATURITIES.index("M2"):
        if not any((capsule / name).is_file() for name in ("run.sh", "run.bat")):
            fail(f"{tool_id}: для {maturity} нужен run.sh или run.bat")

    if MATURITIES.index(maturity) >= MATURITIES.index("M3"):
        check_m3(tool_id, passport, readme_text)
    return {"maturity": maturity, "status": status, "smoke": get("checks", "smoke")}


def check_m3(tool_id: str, passport: configparser.ConfigParser, readme_text: str) -> None:
    capsule = TOOLS / tool_id
    get = lambda section, key: passport.get(section, key, fallback="").strip()  # noqa: E731

    changelog = get("tool", "changelog")
    if not changelog or not (capsule / changelog).is_file():
        fail(f"{tool_id}: M3 требует CHANGELOG ([tool] changelog)")
    version = get("tool", "version")
    if version not in (capsule / changelog).read_text(encoding="utf-8"):
        fail(f"{tool_id}: в {changelog} нет записи о версии {version}")

    contract_doc, contract_version = get("data", "contract_doc"), get("data", "contract_version")
    if not contract_doc or not (capsule / contract_doc).is_file():
        fail(f"{tool_id}: M3 требует документ контракта ([data] contract_doc)")
    if not contract_version.isdigit():
        fail(f"{tool_id}: [data] contract_version должен быть целым числом")
    if f"Версия контракта: {contract_version}" not in (capsule / contract_doc).read_text(encoding="utf-8"):
        fail(f"{tool_id}: в {contract_doc} нет строки «Версия контракта: {contract_version}»")

    regression = get("checks", "regression")
    if not regression or not (capsule / regression).exists():
        fail(f"{tool_id}: M3 требует регрессионные эталоны ([checks] regression)")
    if (capsule / regression).is_dir() and not any((capsule / regression).iterdir()):
        fail(f"{tool_id}: каталог эталонов {regression} пуст")
    if len(get("checks", "tested_scope")) < 40:
        fail(f"{tool_id}: M3 требует честный [checks] tested_scope")

    smoke = get("checks", "smoke")
    script = smoke_script(tool_id, smoke)
    if not script.is_file():
        fail(f"{tool_id}: smoke-скрипт {script.relative_to(ROOT).as_posix()} не найден")
    for section in ("## Проверка", "CHANGELOG.md"):
        if section not in readme_text:
            fail(f"{tool_id}: в README нет «{section}»")
    if contract_doc not in readme_text:
        fail(f"{tool_id}: README не ссылается на {contract_doc}")


def smoke_script(tool_id: str, smoke: str) -> Path:
    parts = shlex.split(smoke)
    if len(parts) != 2 or parts[0] not in {"python", "node"}:
        fail(f"{tool_id}: [checks] smoke должен иметь вид «python scripts/smoke_test.py» или «node scripts/smoke_test.js»")
    return TOOLS / tool_id / parts[1]


def check_rust_and_node() -> None:
    for cargo in sorted(TOOLS.glob("*/Cargo.toml")):
        text = cargo.read_text(encoding="utf-8")
        if '= "*"' in text:
            fail(f"wildcard dependency in {cargo.relative_to(ROOT).as_posix()}")
        if not (cargo.parent / "Cargo.lock").is_file():
            fail(f"{cargo.parent.name}: рядом с Cargo.toml нет Cargo.lock")
    for package in sorted(TOOLS.glob("*/package.json")):
        data = json.loads(package.read_text(encoding="utf-8"))
        for section in ("dependencies", "devDependencies"):
            for name, version in (data.get(section) or {}).items():
                if version in {"latest", "*"}:
                    fail(f"{package.parent.name}: {section}.{name} uses {version}")


def run_smoke(tool_id: str, smoke: str, cargo_target: str) -> list[str]:
    """Запустить smoke капсулы. Возвращает строки вывода, сообщающие о пропусках."""
    script = smoke_script(tool_id, smoke)
    runner = shlex.split(smoke)[0]
    if runner == "node":
        node = shutil.which("node")
        if node is None:
            print(f"{tool_id}: node не найден, smoke ПРОПУЩЕН")
            return [f"{tool_id}: node не найден, smoke не запускался"]
        command = [node, str(script)]
    else:
        command = [sys.executable, "-B", str(script)]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Rust-капсулы собираются только во временный каталог, никогда в свой target/.
    env["CARGO_TARGET_DIR"] = str(Path(cargo_target) / tool_id)
    result = subprocess.run(command, cwd=TOOLS / tool_id, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = result.stdout.strip()
    if result.returncode != 0:
        print(output)
        print(result.stderr, file=sys.stderr)
        fail(f"{tool_id}: smoke failed")
    if not output.endswith(f"{tool_id} smoke passed"):
        print(output)
        fail(f"{tool_id}: smoke не напечатал итоговую строку «{tool_id} smoke passed»")
    print(output)
    return [f"{tool_id}: {line.strip()}" for line in output.splitlines() if any(marker in line.lower() for marker in SKIP_MARKERS)]


def main(argv: list[str]) -> int:
    static_only = "--static" in argv
    unknown = [arg for arg in argv if arg != "--static"]
    if unknown:
        fail(f"неизвестные аргументы: {unknown}; допустим только --static")

    registry = read_registry()
    ids = capsule_ids()
    missing, extra = sorted(set(registry) - set(ids)), sorted(set(ids) - set(registry))
    if missing:
        fail(f"в TOOLS.md есть инструменты без капсулы: {missing}")
    if extra:
        fail(f"в tools/ есть капсулы, которых нет в TOOLS.md: {extra}")

    capsules = {tool_id: check_capsule(tool_id, registry[tool_id]) for tool_id in ids}
    check_payload()
    check_rust_and_node()
    print(f"Паспорта и реестр согласованы: капсул {len(capsules)}, из них M3 и выше: "
          f"{sum(1 for item in capsules.values() if MATURITIES.index(item['maturity']) >= 2)}")

    if static_only:
        print("smoke-тесты не запускались (--static)")
        print("check_tools_shelf passed")
        return 0

    before = shelf_listing()
    skipped: list[str] = []
    with tempfile.TemporaryDirectory(prefix="diy_shelf_cargo_") as cargo_target:
        for tool_id in ids:
            skipped.extend(run_smoke(tool_id, capsules[tool_id]["smoke"], cargo_target))
    after = shelf_listing()
    if before != after:
        changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
        fail(f"smoke-тесты изменили файлы полки: {changed[:20]}")

    if skipped:
        print()
        print("Не проверено автоматически (по сообщениям smoke-тестов):")
        for line in skipped:
            print(f"  - {line}")
    print("check_tools_shelf passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
