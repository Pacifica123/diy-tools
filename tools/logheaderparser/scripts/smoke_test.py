"""Smoke- и регрессионная проверка logheaderparser.

Собирает инструмент через cargo и сравнивает JSON-отчёты с examples/output_expected.
Пишет только во временный каталог: ни отчёты, ни каталог сборки в капсулу не попадают.
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
TOOL_ID = "logheaderparser"

# имя входа, дополнительные аргументы, файл эталона
CASES = [
    ("sample.log", [], "sample.report.json"),
    ("журнал сервиса.log", [], "журнал сервиса.report.json"),
    ("журнал сервиса.log", ["--max-patterns", "3", "--examples", "0"], "журнал сервиса.limits.report.json"),
]


def fail(message: str) -> None:
    raise SystemExit(f"{TOOL_ID} smoke FAILED: {message}")


def capsule_listing() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and "target" not in path.relative_to(ROOT).parts
    )


def check_passport() -> int:
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
    for _name, _args, expected_name in CASES:
        expected = json.loads((EXPECTED / expected_name).read_text(encoding="utf-8"))
        if expected.get("contract_version") != contract:
            fail(f"эталон {expected_name} записан для другой версии контракта")
    return contract


def run_tool(cargo: str, env: dict[str, str], cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    command = [cargo, "run", "--quiet", "--locked", "--manifest-path", str(ROOT / "Cargo.toml"), "--", *args]
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    before = capsule_listing()
    check_passport()
    cargo = shutil.which("cargo")
    if cargo is None:
        source = (ROOT / "src" / "main.rs").read_text(encoding="utf-8")
        for marker in ("BufReader", "progress_lines", "max_patterns"):
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
        out_dir = work / "отчёты с пробелом"
        out_dir.mkdir()

        for index, (name, extra, expected_name) in enumerate(CASES):
            report_path = out_dir / f"report_{index}.json"
            result = run_tool(cargo, env, work, [str(INPUT / name), "--json", str(report_path), "--progress-lines", "0", *extra])
            if result.returncode != 0:
                fail(f"{name} {extra}: код возврата {result.returncode}\n{result.stdout}\n{result.stderr}")
            for marker in ("Готово.", "Обработано строк:", "Найдено шаблонов:", "Отчёт:"):
                if marker not in result.stdout:
                    fail(f"{name}: в итоговой сводке нет строки «{marker}»\n{result.stdout}")
            actual = json.loads(report_path.read_text(encoding="utf-8"))
            expected = json.loads((EXPECTED / expected_name).read_text(encoding="utf-8"))
            actual["file"] = expected["file"]  # путь к входу зависит от машины
            if actual != expected:
                fail(
                    f"отчёт для {name} {extra} отличается от эталона {expected_name}\n"
                    f"получено:\n{json.dumps(actual, ensure_ascii=False, indent=2)}"
                )

        # Флаг S: прогресс идёт в stderr и не смешивается со сводкой.
        progress = run_tool(cargo, env, work, [str(INPUT / "журнал сервиса.log"), "--progress-lines", "5", "--top", "1"])
        if progress.returncode != 0 or progress.stderr.count("обработано строк:") != 2:
            fail(f"ожидались две строки прогресса в stderr\n{progress.stderr}")
        if "обработано строк:" in progress.stdout:
            fail("строки прогресса попали в stdout")

        # Ошибка входа: понятное сообщение и ненулевой код, отчёт не создаётся.
        missing_report = out_dir / "missing.json"
        missing = run_tool(cargo, env, work, [str(work / "нет такого файла.log"), "--json", str(missing_report)])
        if missing.returncode == 0 or "не удалось открыть лог" not in missing.stderr:
            fail(f"нет понятной ошибки для отсутствующего файла\n{missing.stderr}")
        if missing_report.exists():
            fail("отчёт создан, хотя вход не открылся")

    after = capsule_listing()
    if before != after:
        fail(f"проверка изменила состав капсулы: {sorted(set(before) ^ set(after))}")
    print(f"{TOOL_ID} smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
