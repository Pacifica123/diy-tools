"""Smoke- и регрессионная проверка zapret_strategy_extractor.

Собирает инструмент через cargo и сравнивает preset, статистику и список событий с
examples/output_expected. Пишет только во временный каталог: ни результаты, ни каталог
сборки в капсулу не попадают.
"""
from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples" / "input"
EXPECTED = ROOT / "examples" / "output_expected"
TOOL_ID = "zapret_strategy_extractor"
SOURCE_LOG_PREFIX = "# Source log: "

# каталог эталона, имя входного лога, дополнительные аргументы
CASES = [
    ("orchestra_default", "orchestra сессия.log", []),
    (
        "orchestra_base_preset",
        "orchestra сессия.log",
        [
            "--base-preset", str(INPUT / "base_preset.txt"), "--include-success-only", "--no-hostlist-domains",
            "--max-blocks", "3", "--min-locks", "2", "--tcp-filter", "443", "--udp-filter", "443,50000-65535",
        ],
    ),
    ("sample_orchestra", "sample_orchestra.log", []),
]


def fail(message: str) -> None:
    raise SystemExit(f"{TOOL_ID} smoke FAILED: {message}")


def capsule_listing() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and "target" not in path.relative_to(ROOT).parts
    )


def check_passport() -> None:
    passport = configparser.ConfigParser()
    passport.read(ROOT / "tool.ini", encoding="utf-8")
    contract = passport.getint("data", "contract_version")
    source = (ROOT / "src" / "main.rs").read_text(encoding="utf-8")
    if f"const CONTRACT_VERSION: u32 = {contract};" not in source:
        fail("contract_version в tool.ini и CONTRACT_VERSION в src/main.rs расходятся")
    version = passport.get("tool", "version")
    cargo_toml = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
    if f'version = "{version}"' not in cargo_toml:
        fail(f"версия {version} из tool.ini не найдена в Cargo.toml")
    if 'version = "*"' in cargo_toml:
        fail("в Cargo.toml есть зависимость с версией *")
    for case, _name, _args in CASES:
        stats = json.loads((EXPECTED / case / "stats.json").read_text(encoding="utf-8"))
        if stats.get("contract_version") != contract:
            fail(f"эталон {case}/stats.json записан для другой версии контракта")
        if not stats.get("notes"):
            fail(f"в эталоне {case}/stats.json нет пометок best-effort")


def normalize_preset(text: str, source_name: str) -> str:
    lines = [
        f"{SOURCE_LOG_PREFIX}<input>/{source_name}" if line.startswith(SOURCE_LOG_PREFIX) else line
        for line in text.split("\n")
    ]
    return "\n".join(lines)


def run_tool(cargo: str, env: dict[str, str], cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    command = [cargo, "run", "--quiet", "--locked", "--manifest-path", str(ROOT / "Cargo.toml"), "--", *args]
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    before = capsule_listing()
    check_passport()
    cargo = shutil.which("cargo")
    if cargo is None:
        source = (ROOT / "src" / "main.rs").read_text(encoding="utf-8")
        for marker in ("best-effort", "write_events_tsv", "progress_lines", "BufReader"):
            if marker not in source:
                fail(f"в src/main.rs нет {marker}")
        print("cargo не найден: проверены только исходники, паспорт и эталоны; сборка и регрессия ПРОПУЩЕНЫ")
        print(f"{TOOL_ID} smoke passed")
        return 0

    with tempfile.TemporaryDirectory(prefix=f"{TOOL_ID}_smoke_") as tmp:
        work = Path(tmp)
        env = os.environ.copy()
        # Сборка никогда не идёт в target/ капсулы: проверка не должна оставлять следов.
        env.setdefault("CARGO_TARGET_DIR", str(work / "cargo-target"))
        inputs_before = {path.name: path.read_bytes() for path in INPUT.iterdir() if path.is_file()}

        for case, name, extra in CASES:
            out_dir = work / f"результат {case}"
            out_dir.mkdir()
            preset, stats, events = out_dir / "preset.txt", out_dir / "stats.json", out_dir / "events.tsv"
            result = run_tool(cargo, env, work, [
                str(INPUT / name), "--preset-out", str(preset), "--stats-out", str(stats), "--events-out", str(events),
                "--progress-lines", "0", *extra,
            ])
            if result.returncode != 0:
                fail(f"{case}: код возврата {result.returncode}\n{result.stdout}\n{result.stderr}")
            for marker in ("Готово.", "Обработано строк:", "Создано блоков preset:", "Результат", "Отчёт"):
                if marker not in result.stdout:
                    fail(f"{case}: в итоговой сводке нет «{marker}»\n{result.stdout}")
            for path in (preset, stats, events):
                if not path.is_file():
                    fail(f"{case}: не создан {path.name}")

            actual_stats = json.loads(stats.read_text(encoding="utf-8"))
            expected_stats = json.loads((EXPECTED / case / "stats.json").read_text(encoding="utf-8"))
            actual_stats["source_log"] = expected_stats["source_log"]  # путь к логу зависит от машины
            if actual_stats != expected_stats:
                fail(f"{case}: stats.json отличается от эталона\nполучено:\n{json.dumps(actual_stats, ensure_ascii=False, indent=2)}")

            actual_events = events.read_text(encoding="utf-8")
            if actual_events != (EXPECTED / case / "events.tsv").read_text(encoding="utf-8"):
                fail(f"{case}: events.tsv отличается от эталона\nполучено:\n{actual_events}")

            actual_preset = normalize_preset(preset.read_text(encoding="utf-8"), name)
            if actual_preset != (EXPECTED / case / "preset.txt").read_text(encoding="utf-8"):
                fail(f"{case}: preset.txt отличается от эталона\nполучено:\n{actual_preset}")
            # Флаг G: результат помечен как best-effort и требует ручной проверки.
            if "best-effort" not in actual_preset:
                fail(f"{case}: в preset нет пометки best-effort")

        # Флаг G: исходные данные не перезаписываются.
        if inputs_before != {path.name: path.read_bytes() for path in INPUT.iterdir() if path.is_file()}:
            fail("инструмент изменил файлы в examples/input")

        # Флаг S: прогресс идёт в stderr.
        progress_dir = work / "progress"
        progress_dir.mkdir()
        progress = run_tool(cargo, env, progress_dir, [str(INPUT / "orchestra сессия.log"), "--progress-lines", "10"])
        if progress.returncode != 0 or progress.stderr.count("обработано строк:") != 3:
            fail(f"ожидались три строки прогресса в stderr\n{progress.stderr}")
        # Без явных путей результаты пишутся в текущую папку под именами по умолчанию.
        for default_name in ("locked_strategies_preset.txt", "strategy_stats.json", "strategy_events.tsv"):
            if not (progress_dir / default_name).is_file():
                fail(f"в текущей папке не создан {default_name}")

        # Ошибка входа: понятное сообщение, ненулевой код, файлы не создаются.
        missing_dir = work / "missing"
        missing_dir.mkdir()
        missing = run_tool(cargo, env, missing_dir, [str(work / "нет такого лога.log")])
        if missing.returncode == 0 or "не удалось открыть лог" not in missing.stderr:
            fail(f"нет понятной ошибки для отсутствующего лога\n{missing.stderr}")
        if any(missing_dir.iterdir()):
            fail("созданы выходные файлы, хотя лог не открылся")

    after = capsule_listing()
    if before != after:
        fail(f"проверка изменила состав капсулы: {sorted(set(before) ^ set(after))}")
    print(f"{TOOL_ID} smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
