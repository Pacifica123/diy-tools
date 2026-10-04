"""Smoke- и регрессионный тест капсулы markdown_splitter.

Запуск из любой папки: python3 /путь/к/капсуле/scripts/smoke_test.py
Пишет только во временную папку, сеть и сторонние пакеты не нужны.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import configparser  # noqa: E402
import difflib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

TOOL_ID = "markdown_splitter"
ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src" / "cli.py"
INPUT_DIR = ROOT / "examples" / "input"
EXPECTED_DIR = ROOT / "examples" / "output_expected"

# Регрессионные примеры: (файл из examples/input, значение --max-size).
# Эталон лежит в examples/output_expected/<имя файла без расширения>/.
CASES = [
    ("sample.md", "200"),
    ("Большой документ с пробелами.md", "420"),
    ("oversized_block.md", "300"),
    ("frontmatter.md", "300"),
    ("без заголовков.md", "260"),
]
MAIN_CASE = "Большой документ с пробелами.md"
OVERSIZED_CASE = "oversized_block.md"

ATX_RE = re.compile(r"^ {0,3}#{1,6}[ \t]")
SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")


class SmokeFailure(Exception):
    pass


def check(condition: object, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Запускает настоящий CLI отдельным процессом, как это делает пользователь."""
    result = subprocess.run(
        [sys.executable, "-B", str(CLI), *args],
        cwd=str(cwd),
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace")
    result.stderr = result.stderr.decode("utf-8", errors="replace")
    return result


def describe(result: subprocess.CompletedProcess) -> str:
    return f"код возврата {result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"


def snapshot(directory: Path) -> dict[str, bytes | None]:
    """Полный снимок дерева: относительный путь -> содержимое (None для папок)."""
    state: dict[str, bytes | None] = {}
    for path in sorted(directory.rglob("*")):
        rel = path.relative_to(directory).as_posix()
        state[rel] = path.read_bytes() if path.is_file() else None
    return state


def capsule_listing() -> list[str]:
    return sorted(path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*"))


def normalized_source(path: Path) -> str:
    text = path.read_bytes().decode("utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def nonblank_lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.strip()]


def front_matter_length(lines: list[str]) -> int:
    """Сколько непустых строк в начале занимает YAML front matter (0, если его нет)."""
    if lines and lines[0].strip() == "---":
        for position in range(1, len(lines)):
            if lines[position].strip() in {"---", "..."}:
                return position + 1
    return 0


def heading_length_at(lines: list[str], position: int) -> int:
    """Длина заголовка в строках, начиная с position: 1 (ATX), 2 (Setext) или 0."""
    if position >= len(lines):
        return 0
    if ATX_RE.match(lines[position]):
        return 1
    if position + 1 < len(lines) and SETEXT_UNDERLINE_RE.match(lines[position + 1]):
        return 2
    return 0


def compare_with_expected(actual: Path, expected: Path, label: str) -> None:
    check(expected.is_dir(), f"{label}: нет эталонной папки {expected}")
    actual_names = sorted(p.name for p in actual.iterdir())
    expected_names = sorted(p.name for p in expected.iterdir())
    check(
        actual_names == expected_names,
        f"{label}: набор файлов отличается от эталона.\n  получено: {actual_names}\n  эталон:   {expected_names}",
    )
    for name in expected_names:
        got = (actual / name).read_bytes()
        want = (expected / name).read_bytes()
        if got != want:
            diff = difflib.unified_diff(
                want.decode("utf-8", errors="replace").splitlines(),
                got.decode("utf-8", errors="replace").splitlines(),
                fromfile=f"эталон/{name}",
                tofile=f"получено/{name}",
                lineterm="",
            )
            shown = "\n".join(list(diff)[:60])
            raise SmokeFailure(f"{label}: файл {name} отличается от эталона:\n{shown}")


def check_invariants(source: Path, out: Path, max_bytes: int, label: str, parse_blocks) -> dict:
    """Инварианты нарезки, проверяемые по результату на диске."""
    index_path = out / "index.json"
    check(index_path.is_file(), f"{label}: нет аудит-файла index.json")
    report = json.loads(index_path.read_text(encoding="utf-8"))

    check(report.get("contract_version") == 1, f"{label}: в index.json нет contract_version = 1")
    for key in ("formatVersion", "source", "maxBytes", "parts", "warnings"):
        check(key in report, f"{label}: в index.json нет поля {key}")
    check(report["source"] == source.name, f"{label}: index.json source = {report['source']!r}")
    check(report["maxBytes"] == max_bytes, f"{label}: index.json maxBytes = {report['maxBytes']!r}")
    check(str(out) not in index_path.read_text(encoding="utf-8"), f"{label}: в index.json попал абсолютный путь")

    parts = report["parts"]
    check(parts, f"{label}: список частей пуст")
    listed = [part["file"] for part in parts]
    on_disk = sorted(p.name for p in out.iterdir() if p.name != "index.json")
    check(sorted(listed) == on_disk, f"{label}: index.json перечисляет {sorted(listed)}, а на диске {on_disk}")
    check([part["index"] for part in parts] == list(range(1, len(parts) + 1)), f"{label}: нумерация частей нарушена")

    source_text = normalized_source(source)
    source_lines = nonblank_lines(source_text)
    source_front = front_matter_length(source_lines)
    restored: list[str] = []
    oversized_count = 0
    for part in parts:
        number = part["index"]
        where = f"{label}: часть {number} ({part['file']})"
        for key in ("title", "sizeBytes", "contextHeadingAdded", "oversized"):
            check(key in part, f"{where}: нет поля {key}")
        data = (out / part["file"]).read_bytes()
        check(b"\r" not in data, f"{where}: в части остались символы CR")
        check(part["sizeBytes"] == len(data), f"{where}: sizeBytes {part['sizeBytes']} != {len(data)} на диске")
        check(part["oversized"] == (len(data) > max_bytes), f"{where}: признак oversized не соответствует размеру")
        if part["oversized"]:
            oversized_count += 1
            check(
                any(w.startswith(f"часть {number} ") for w in report["warnings"]),
                f"{where}: превышает лимит {max_bytes}, но предупреждения в index.json нет",
            )
        text = data.decode("utf-8")
        check(text.endswith("\n") and not text.startswith("\n"), f"{where}: часть должна начинаться с текста и кончаться переводом строки")
        try:
            parse_blocks(text)
        except Exception as exc:  # незакрытый fence внутри части = разорванный блок
            raise SmokeFailure(f"{where}: часть не разбирается как самостоятельный Markdown: {exc}") from exc

        lines = nonblank_lines(text)
        start = front_matter_length(lines) if number == 1 and source_front else 0
        heading_len = heading_length_at(lines, start)
        check(heading_len > 0, f"{where}: часть не начинается с заголовка")
        if part["contextHeadingAdded"]:
            # Добавленный (синтетический или повторённый) заголовок — первый заголовок части.
            lines = lines[:start] + lines[start + heading_len:]
            check(lines[start:], f"{where}: кроме добавленного заголовка в части ничего нет")
        restored.extend(lines)

    check(
        oversized_count == len(report["warnings"]),
        f"{label}: предупреждений {len(report['warnings'])}, частей сверх лимита {oversized_count}",
    )
    if restored != source_lines:
        diff = difflib.unified_diff(source_lines, restored, fromfile="исходник", tofile="склейка частей", lineterm="")
        shown = "\n".join(list(diff)[:60])
        raise SmokeFailure(f"{label}: склейка частей без добавленных заголовков не совпадает с исходником:\n{shown}")
    return report


def test_core_units(cli) -> None:
    check(cli.parse_size("1M") == 1024 * 1024, "parse_size('1M')")
    check(cli.parse_size("1.5K") == 1536, "parse_size('1.5K')")
    check(cli.parse_size("700") == 700, "parse_size('700')")
    sample = "# Док\n\n```python\n# не заголовок\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nЗаголовок\n=========\n"
    kinds = [block.kind for block in cli.parse_blocks(sample) if block.kind != "blank"]
    check(kinds == ["heading", "fence", "table", "heading"], f"parse_blocks вернул {kinds}")

    def split(text: str, limit: int):
        return cli.split_blocks(cli.parse_blocks(text), limit, "doc")

    # Исправленные в 0.3.0 ошибки (см. CHANGELOG.md).
    chunks, _ = split("один абзац\n\nвторой абзац\n\nтретий абзац\n", 40)
    check(all(c.text.count("# doc") == 1 for c in chunks), "синтетический заголовок продублирован")
    chunks, warnings = split("# H\n\n```\n" + "x" * 100 + "\n```\n", 50)
    check(len(chunks) == 1 and len(warnings) == 1, "заголовок оторван от своего неделимого блока")
    chunks, _ = split("# A\n\n" + "a" * 20 + "\n\n# B\n\nbbb\n", 26)
    check([c.text for c in chunks] == ["# A\n\n" + "a" * 20 + "\n", "# B\n\nbbb\n"], "висящий повторный заголовок перед новой секцией")
    chunks, _ = split("# A\n\n" + "a" * 20 + "\n\n\n", 26)
    check(len(chunks) == 1, "создана часть из одного повторённого заголовка")
    chunks, _ = split("# A\n\nтекст раздела\n\n## B\n\nтекст подраздела\n", 45)
    check([c.title for c in chunks] == ["A", "B"] and not chunks[0].text.rstrip().endswith("## B"), "заголовок остался в конце части без текста")
    chunks, _ = split("# A\n\n## B\n\nтекст\n", 1000)
    check(chunks[0].title == "A", "часть должна называться по первому заголовку")
    chunks, warnings = split("# A\n\nabc", 8)
    check(chunks[0].size_bytes == 9 and chunks[0].oversized and len(warnings) == 1, "размер части считается без завершающего перевода строки")


def test_regression(cli, tmp: Path) -> dict[str, dict]:
    reports: dict[str, dict] = {}
    work = tmp / "вход с пробелами"
    work.mkdir()
    for name, max_size in CASES:
        label = f"пример «{name}»"
        original = INPUT_DIR / name
        check(original.is_file(), f"{label}: нет входного файла {original}")
        source = work / name
        shutil.copyfile(original, source)
        out_rel = Path("результат") / Path(name).stem
        # Относительные пути от текущей папки пользователя, пробелы и кириллица.
        result = run_cli([name, "--max-size", max_size, "--output-dir", str(out_rel), "--json"], cwd=work)
        check(result.returncode == 0, f"{label}: CLI завершился с ошибкой: {describe(result)}")
        out = work / out_rel
        check(out.is_dir(), f"{label}: выходная папка не создана")
        check(source.read_bytes() == original.read_bytes(), f"{label}: исходный файл изменён")

        compare_with_expected(out, EXPECTED_DIR / Path(name).stem, label)
        report = check_invariants(source, out, int(max_size), label, cli.parse_blocks)

        printed = json.loads(result.stdout)
        check(printed.get("outputDir") == str(out_rel), f"{label}: outputDir в stdout = {printed.get('outputDir')!r}")
        check(printed.get("dryRun") is False, f"{label}: dryRun в stdout должен быть false")
        printed.pop("outputDir")
        printed.pop("dryRun")
        check(printed == report, f"{label}: JSON в stdout расходится с index.json")
        reports[name] = report

    check(any(r["warnings"] for r in reports.values()), "ни один пример не проверяет путь с предупреждением о превышении лимита")
    check(not reports[MAIN_CASE]["warnings"], "основной пример не должен давать предупреждений")
    titles = [part["title"] for part in reports[MAIN_CASE]["parts"]]
    check(len(titles) != len(set(titles)), "основной пример не проверяет продолжение секции с повтором заголовка")
    return reports


def test_crlf_and_bom(cli, tmp: Path) -> None:
    """Тот же документ с CRLF и BOM даёт побайтно тот же результат (на выходе всегда LF)."""
    work = tmp / "crlf"
    work.mkdir()
    max_size = dict(CASES)[MAIN_CASE]
    text = normalized_source(INPUT_DIR / MAIN_CASE)
    source = work / MAIN_CASE
    source.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
    result = run_cli([MAIN_CASE, "--max-size", max_size, "--output-dir", "out"], cwd=work)
    check(result.returncode == 0, f"CRLF+BOM: CLI завершился с ошибкой: {describe(result)}")
    compare_with_expected(work / "out", EXPECTED_DIR / Path(MAIN_CASE).stem, "CRLF+BOM")
    check_invariants(source, work / "out", int(max_size), "CRLF+BOM", cli.parse_blocks)


def test_dry_run(tmp: Path, reports: dict[str, dict]) -> None:
    work = tmp / "dry run"
    work.mkdir()
    for name, max_size in CASES:
        shutil.copyfile(INPUT_DIR / name, work / name)
    before = snapshot(work)
    for name, max_size in CASES:
        label = f"dry-run «{name}»"
        result = run_cli([name, "--max-size", max_size, "--dry-run", "--json"], cwd=work)
        check(result.returncode == 0, f"{label}: {describe(result)}")
        plan = json.loads(result.stdout)
        check(plan.get("dryRun") is True and plan.get("contract_version") == 1, f"{label}: нет dryRun/contract_version")
        expected_parts = [{k: v for k, v in part.items() if k != "file"} for part in reports[name]["parts"]]
        check(plan["parts"] == expected_parts, f"{label}: план dry-run расходится с настоящим результатом")
        check(plan["warnings"] == reports[name]["warnings"], f"{label}: предупреждения dry-run расходятся с настоящими")
        result = run_cli([name, "--max-size", max_size, "--dry-run", "--output-dir", "план"], cwd=work)
        check(result.returncode == 0, f"{label} (текст): {describe(result)}")
        check("пробный запуск" in result.stdout and "Будет создано:" in result.stdout, f"{label}: нет итоговой сводки dry-run")
    check(snapshot(work) == before, "--dry-run что-то записал на диск")


def test_safety_and_summary(tmp: Path, reports: dict[str, dict]) -> None:
    work = tmp / "защита"
    work.mkdir()
    name = OVERSIZED_CASE
    max_size = dict(CASES)[name]
    shutil.copyfile(INPUT_DIR / name, work / name)

    # Обычный текстовый режим: итоговая сводка и предупреждения в stderr.
    result = run_cli([name, "--max-size", max_size], cwd=work)
    check(result.returncode == 0, f"текстовый режим: {describe(result)}")
    count = len(reports[name]["parts"])
    for needle in ("Готово.", f"Создано: {count}", f"Предупреждений: {len(reports[name]['warnings'])}", "Ошибок: 0", "Результат: ", "Отчёт: "):
        check(needle in result.stdout, f"в итоговой сводке нет строки «{needle}»:\n{result.stdout}")
    check(result.stderr.count("Предупреждение:") == len(reports[name]["warnings"]), f"предупреждения не выведены в stderr:\n{result.stderr}")
    default_out = work / (Path(name).stem + "_parts")
    check((default_out / "index.json").is_file(), "папка по умолчанию <имя>_parts не создана рядом с исходником")

    # Повторный запуск не трогает существующую папку, а создаёт соседнюю.
    before = snapshot(default_out)
    result = run_cli([name, "--max-size", max_size], cwd=work)
    check(result.returncode == 0, f"повторный запуск: {describe(result)}")
    check(snapshot(default_out) == before, "повторный запуск изменил существующую папку результата")
    check((work / (Path(name).stem + "_parts_2") / "index.json").is_file(), "повторный запуск не создал <имя>_parts_2")

    # Непустая явная выходная папка не перезаписывается.
    before = snapshot(work)
    result = run_cli([name, "--max-size", "100", "--output-dir", default_out.name], cwd=work)
    check(result.returncode == 1, f"непустая выходная папка должна давать код 1: {describe(result)}")
    check("выходная папка не пуста" in result.stderr, f"нет понятного сообщения о непустой папке:\n{result.stderr}")
    result = run_cli([name, "--output-dir", name], cwd=work)
    check(result.returncode == 1 and "не является папкой" in result.stderr, f"выходной путь-файл: {describe(result)}")
    check(snapshot(work) == before, "отказ от записи всё же изменил файлы")

    # Ошибки входа: понятное сообщение, код возврата, ничего не создано.
    (work / "broken.md").write_text("# X\n\n```python\nprint(1)\n", encoding="utf-8")
    (work / "empty.md").write_text("", encoding="utf-8")
    (work / "cp1251.md").write_bytes("# Заголовок\n".encode("cp1251"))
    before = snapshot(work)
    for file_name, code, needle in (
        ("broken.md", 1, "незакрытый fenced code block"),
        ("empty.md", 1, "исходный файл пуст"),
        ("cp1251.md", 1, "файл должен быть UTF-8"),
        ("нет такого.md", 2, "файл не найден"),
    ):
        result = run_cli([file_name, "--output-dir", "out_errors"], cwd=work)
        check(result.returncode == code, f"{file_name}: ожидался код {code}: {describe(result)}")
        check(needle in result.stderr, f"{file_name}: нет сообщения «{needle}»:\n{result.stderr}")
        check("Traceback" not in result.stderr, f"{file_name}: вместо сообщения выведен traceback")
    check(snapshot(work) == before, "ошибочный запуск оставил файлы на диске")

    result = run_cli(["--help"], cwd=work)
    check(result.returncode == 0 and "--max-size" in result.stdout and "--dry-run" in result.stdout, f"--help: {describe(result)}")


def test_launchers(tmp: Path) -> str:
    bat = (ROOT / "run.bat").read_text(encoding="utf-8")
    sh_text = (ROOT / "run.sh").read_text(encoding="utf-8")
    check("%~dp0src\\cli.py" in bat and "cd /d" not in bat, "run.bat должен вызывать cli.py по абсолютному пути без cd")
    check('"$DIR/src/cli.py"' in sh_text and "\ncd " not in sh_text, "run.sh должен вызывать cli.py по абсолютному пути без cd")

    sh = shutil.which("sh")
    python3 = shutil.which("python3")
    if not sh or not python3:
        return "run.sh не запускался (в PATH нет sh или python3); run.bat проверен только статически"
    probe = subprocess.run([python3, "-c", "import sys; sys.exit(sys.version_info < (3, 11))"], env=child_env())
    if probe.returncode != 0:
        return "run.sh не запускался (python3 из PATH старше 3.11); run.bat проверен только статически"

    work = tmp / "запуск через run.sh"
    work.mkdir()
    name = MAIN_CASE
    max_size = dict(CASES)[name]
    shutil.copyfile(INPUT_DIR / name, work / name)
    result = subprocess.run(
        [sh, str(ROOT / "run.sh"), name, "--max-size", max_size, "--output-dir", "части"],
        cwd=str(work),
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    out = result.stdout.decode("utf-8", errors="replace")
    err = result.stderr.decode("utf-8", errors="replace")
    check(result.returncode == 0, f"run.sh с относительным путём: код {result.returncode}\n{out}\n{err}")
    compare_with_expected(work / "части", EXPECTED_DIR / Path(name).stem, "run.sh")
    return "run.sh запущен из чужой текущей папки с относительным путём; run.bat проверен только статически"


def test_passport(cli) -> None:
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(ROOT / "tool.ini", encoding="utf-8")

    def value(section: str, key: str) -> str:
        found = ini.get(section, key, fallback="")
        check(found, f"в tool.ini нет [{section}] {key}")
        return found

    version = value("tool", "version")
    check(value("tool", "maturity") == "M3", "в tool.ini maturity должен быть M3")
    check(value("data", "contract_version") == str(cli.CONTRACT_VERSION), "contract_version в tool.ini и в коде расходятся")
    contract_path = ROOT / value("data", "contract_doc")
    check(contract_path.is_file(), f"нет файла контракта {contract_path}")
    check(f"Версия контракта: {cli.CONTRACT_VERSION}" in contract_path.read_text(encoding="utf-8"), "версия в docs/CONTRACT.md расходится с кодом")
    changelog_path = ROOT / value("tool", "changelog")
    check(changelog_path.is_file(), f"нет файла {changelog_path}")
    changelog = changelog_path.read_text(encoding="utf-8")
    first_entry = next((line for line in changelog.splitlines() if line.startswith("## ")), "")
    check(version in first_entry, f"верхняя запись CHANGELOG.md ({first_entry!r}) не про версию {version}")
    check((ROOT / value("checks", "regression")).resolve() == EXPECTED_DIR.resolve(), "[checks] regression в tool.ini не указывает на examples/output_expected")
    check(EXPECTED_DIR.is_dir(), "папка эталонов examples/output_expected не найдена")


def run() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass

    capsule_before = capsule_listing()
    sys.path.insert(0, str(ROOT / "src"))
    import cli  # noqa: E402

    try:
        with tempfile.TemporaryDirectory(prefix=f"{TOOL_ID}_smoke_") as tmp_name:
            tmp = Path(tmp_name)
            test_core_units(cli)
            reports = test_regression(cli, tmp)
            test_crlf_and_bom(cli, tmp)
            test_dry_run(tmp, reports)
            test_safety_and_summary(tmp, reports)
            launcher_note = test_launchers(tmp)
            test_passport(cli)
        capsule_after = capsule_listing()
        check(
            capsule_after == capsule_before,
            "проверка оставила файлы в капсуле: " + ", ".join(sorted(set(capsule_after) ^ set(capsule_before))),
        )
    except SmokeFailure as exc:
        print(f"{TOOL_ID} smoke FAILED: {exc}", file=sys.stderr)
        return 1

    total_parts = sum(len(report["parts"]) for report in reports.values())
    print(f"Регрессия: {len(CASES)} примеров, {total_parts} частей совпали с examples/output_expected; CRLF+BOM дал тот же результат.")
    print("Инварианты: содержимое не потеряно, лимит превышен только с предупреждением, dry-run и непустая папка ничего не пишут.")
    print(f"Запускалки: {launcher_note}.")
    print("Не проверялось: Windows.")
    print(f"{TOOL_ID} smoke passed")
    return 0


if __name__ == "__main__":
    if sys.flags.utf8_mode == 0 and sys.getfilesystemencoding().lower().replace("-", "") != "utf8":
        # Имена примеров содержат кириллицу: при не-UTF-8 локали перезапускаемся в режиме UTF-8.
        raise SystemExit(subprocess.run([sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve())]).returncode)
    raise SystemExit(run())
