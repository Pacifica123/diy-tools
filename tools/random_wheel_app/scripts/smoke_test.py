"""Smoke- и регрессионный тест капсулы random_wheel_app (без GUI).

Запуск из любого каталога:

    python3 scripts/smoke_test.py

Тест прогоняет настоящие слои app/domain и app/storage на файлах из
examples/input и сравнивает результат с examples/output_expected.
Пишет только во временный каталог. PySide6 не нужен: окна не запускаются.

Обновить эталоны после осознанного изменения поведения:

    python3 scripts/smoke_test.py --update-expected
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import ast
import contextlib
import difflib
import importlib.util
import io
import json
import re
import tempfile
import traceback
from pathlib import Path

TOOL_ID = "random_wheel_app"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "examples" / "input"
EXPECTED_DIR = PROJECT_ROOT / "examples" / "output_expected"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.domain.export import export_history_csv, export_history_json, export_history_txt, export_summary
from app.domain.models import CONTRACT_VERSION, SpinOptions, WheelSession
from app.domain.parser import parse_wheel_file
from app.domain.wheel import WheelEngine
from app.storage import autosave
from app.storage.save_load import SessionFormatError, read_session, write_session

TIMESTAMP_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
TIMESTAMP_MARK = "<TIMESTAMP>"
SPINS = 20


class SmokeFailure(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def normalize(text: str) -> str:
    """Убирает только заведомо нестабильное: время и вид переводов строк."""
    text = text.replace("\r\n", "\n")
    text = TIMESTAMP_RE.sub(TIMESTAMP_MARK, text)
    return text.rstrip("\n") + "\n"


def state_of(session: WheelSession) -> dict:
    """Состояние сессии без updated_at (это поле — момент записи файла)."""
    data = session.to_dict()
    data.pop("updated_at")
    return data


def capsule_listing() -> list[tuple[str, int]]:
    """Имена и размеры файлов капсулы: по ним видно, если тест что-то в неё записал."""
    result = []
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if path.is_file():
            result.append((path.relative_to(PROJECT_ROOT).as_posix(), path.stat().st_size))
    return result


def file_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def spin(engine: WheelEngine, count: int) -> list[str]:
    winners = []
    for _ in range(count):
        item, weight, total = engine.select_item()
        record = engine.record_spin(item, weight, total)
        check(bool(TIMESTAMP_RE.fullmatch(record.created_at)), f"Неожиданный формат времени: {record.created_at!r}")
        winners.append(record.label)
    return winners


# --------------------------------------------------------------------------
# 1. Разбор входных TXT
# --------------------------------------------------------------------------

def check_parser(tmp: Path) -> dict[str, str]:
    report = {}
    names = ["sample_equal.txt", "sample_weighted.txt", "список с ошибками.txt"]
    for name in names:
        result = parse_wheel_file(INPUT_DIR / name)
        report[name] = {
            "stats": result.stats(),
            "items": [item.to_dict() for item in result.items],
            "issues": [
                {"line_number": issue.line_number, "text": issue.text, "message": issue.message}
                for issue in result.issues
            ],
        }

    # Тот же файл в других кодировках и с CRLF, из каталога с пробелами и кириллицей.
    odd_dir = tmp / "папка с пробелами"
    odd_dir.mkdir()
    source_text = (INPUT_DIR / "список с ошибками.txt").read_text(encoding="utf-8")
    reference = report["список с ошибками.txt"]["items"]
    variants = {
        "utf-8 с BOM.txt": source_text.encode("utf-8-sig"),
        "cp1251.txt": source_text.encode("cp1251"),
        "utf-8 crlf.txt": source_text.replace("\n", "\r\n").encode("utf-8"),
    }
    for name, payload in variants.items():
        path = odd_dir / name
        path.write_bytes(payload)
        items = [item.to_dict() for item in parse_wheel_file(path).items]
        check(items == reference, f"Файл «{name}» разобран иначе, чем UTF-8-оригинал.")

    return {"parse.json": dump(report)}


# --------------------------------------------------------------------------
# 2. Колесо: сегменты и точная последовательность победителей при seed
# --------------------------------------------------------------------------

def check_wheel() -> dict[str, str]:
    equal_items = parse_wheel_file(INPUT_DIR / "sample_equal.txt").items
    weighted_items = parse_wheel_file(INPUT_DIR / "sample_weighted.txt").items
    messy_items = parse_wheel_file(INPUT_DIR / "список с ошибками.txt").items

    equal_engine = WheelEngine.new(equal_items, SpinOptions(mode="equal", random_seed=42))
    spans = [segment.span for segment in equal_engine.segments()]
    check(spans == [90.0, 90.0, 90.0, 90.0], f"Равный режим: ожидались сегменты по 90°, получено {spans}")

    weighted_engine = WheelEngine.new(weighted_items, SpinOptions(mode="weighted", random_seed=42))
    segments = weighted_engine.segments()
    check(weighted_engine.total_weight() == 37.5, f"Суммарный вес: {weighted_engine.total_weight()}")
    check(abs(segments[1].span / segments[0].span - 2.0) < 1e-9, "Вес 20 должен давать сегмент вдвое больше веса 10.")
    check(segments[0].start_angle == 0.0 and segments[-1].end_angle == 360.0, "Сегменты должны покрывать 0..360°.")
    check(abs(sum(s.probability for s in segments) - 1.0) < 1e-12, "Сумма вероятностей должна быть 1.")

    report: dict[str, object] = {"spins_per_scenario": SPINS}
    report["equal_seed_42"] = spin(equal_engine, SPINS)
    report["weighted_seed_42"] = spin(weighted_engine, SPINS)
    report["weighted_seed_7"] = spin(WheelEngine.new(weighted_items, SpinOptions(mode="weighted", random_seed=7)), SPINS)
    report["messy_weighted_seed_2024"] = spin(
        WheelEngine.new(messy_items, SpinOptions(mode="weighted", random_seed=2024)), SPINS
    )

    # Тот же seed — та же последовательность; выбор без записи не сдвигает её.
    again = WheelEngine.new(weighted_items, SpinOptions(mode="weighted", random_seed=42))
    first = again.select_item()[0].label
    check(again.select_item()[0].label == first, "Повторный выбор без записи вращения должен давать тот же вариант.")
    # GUI после выбора берёт из того же генератора числа для анимации — на победителей это не влияет.
    winners = []
    for _ in range(SPINS):
        item, weight, total = again.select_item()
        again.random.uniform(0.0, 360.0)
        again.random.randint(5, 9)
        winners.append(again.record_spin(item, weight, total).label)
    check(winners == report["weighted_seed_42"], "Числа, потраченные на анимацию, изменили последовательность победителей.")

    # Режим «удалять выпавший вариант»: до опустошения колеса, затем понятная ошибка и сброс.
    removing = WheelEngine.new(equal_items, SpinOptions(mode="equal", random_seed=42, remove_winner=True))
    removed = spin(removing, len(equal_items))
    check(sorted(removed) == sorted(item.label for item in equal_items), "Без повторов должны выпасть все варианты по одному разу.")
    check(removing.session.active_ids == [] and removing.segments() == [], "После всех вращений колесо должно быть пустым.")
    try:
        removing.select_item()
    except ValueError as exc:
        report["empty_wheel_error"] = str(exc)
    else:
        raise SmokeFailure("Пустое колесо должно давать ошибку, а не вариант.")
    removing.reset_active()
    check(len(removing.active_items()) == len(equal_items), "«Вернуть все варианты» должно вернуть все варианты.")
    report["equal_seed_42_remove_winner"] = removed

    # seed = 0: случайный генератор, проверяем только работоспособность.
    unseeded = WheelEngine.new(equal_items, SpinOptions(mode="equal", random_seed=0))
    check(all(label in {i.label for i in equal_items} for label in spin(unseeded, 5)), "seed=0: выпал неизвестный вариант.")

    return {"winners.json": dump(report)}


# --------------------------------------------------------------------------
# 3. Короткая сессия: autosave -> загрузка -> продолжение, история, экспорт
# --------------------------------------------------------------------------

def check_session(tmp: Path) -> dict[str, str]:
    items = parse_wheel_file(INPUT_DIR / "sample_weighted.txt").items
    options = SpinOptions(mode="weighted", random_seed=42)

    straight = WheelEngine.new([*items], SpinOptions(mode="weighted", random_seed=42))
    straight_winners = spin(straight, 8)

    work = tmp / "сессия с пробелами"
    work.mkdir()
    default_autosave = autosave.AUTOSAVE_PATH
    autosave.AUTOSAVE_PATH = work / "autosave колеса.json"
    try:
        check(not autosave.has_autosave(), "Во временном каталоге не должно быть autosave до начала сессии.")
        engine = WheelEngine.new(items, options)
        winners = spin(engine, 5)
        autosave.write_autosave(engine.session)
        check(autosave.has_autosave(), "Autosave не появился после записи.")
        check(sorted(p.name for p in work.iterdir()) == ["autosave колеса.json"], "Рядом с autosave остались лишние файлы.")

        saved_text = autosave.AUTOSAVE_PATH.read_text(encoding="utf-8")
        saved = json.loads(saved_text)
        check(saved.get("contract_version") == CONTRACT_VERSION == 1, "В autosave нет contract_version = 1.")

        restored = autosave.read_autosave()
        check(state_of(restored) == state_of(engine.session), "Состояние после загрузки autosave отличается от сохранённого.")

        # Повторная запись загруженной сессии даёт тот же файл (кроме времени записи).
        autosave.write_autosave(restored)
        check(
            normalize(autosave.AUTOSAVE_PATH.read_text(encoding="utf-8")) == normalize(saved_text),
            "Сохранение -> загрузка -> сохранение изменило файл.",
        )

        resumed = WheelEngine(restored)
        winners += spin(resumed, 3)
        check(winners == straight_winners, "После загрузки autosave последовательность победителей разошлась с непрерывной сессией.")
        check(
            normalize(dump(state_of(resumed.session))) == normalize(dump(state_of(straight.session))),
            "Состояние после продолжения отличается от непрерывной сессии.",
        )
        autosave.write_autosave(resumed.session)
        final_autosave = autosave.AUTOSAVE_PATH.read_text(encoding="utf-8")
    finally:
        autosave.AUTOSAVE_PATH = default_autosave

    history = resumed.session.history
    check(len(history) == 8 and resumed.session.spin_count == 8, "В истории должно быть 8 записей.")

    txt_path, csv_path, json_path = work / "история.txt", work / "история.csv", work / "история.json"
    export_history_txt(history, txt_path)
    export_history_csv(history, csv_path)
    export_history_json(history, json_path)

    csv_bytes = csv_path.read_bytes()
    check(csv_bytes.startswith(b"\xef\xbb\xbf"), "CSV-экспорт должен начинаться с UTF-8 BOM (для Excel).")
    check(csv_bytes.count(b"\r\n") == len(history) + 1 and csv_bytes.count(b"\n") == len(history) + 1,
          "CSV-экспорт: ожидалась строка заголовка и по строке на запись с переводами CRLF.")
    exported = json.loads(json_path.read_text(encoding="utf-8"))
    check(exported.get("contract_version") == 1 and len(exported.get("records", [])) == 8,
          "JSON-экспорт: ожидались contract_version = 1 и 8 записей в records.")

    summary = export_summary(history, csv_path).replace(str(work), "<TMP>").replace("\\", "/")

    # История: очистка не трогает варианты и счётчик вращений.
    resumed.clear_history()
    check(resumed.session.history == [] and resumed.session.spin_count == 8 and len(resumed.active_items()) == 4,
          "«Очистить историю» должна убрать только записи истории.")
    next_winner = spin(resumed, 1)[0]
    check(next_winner == spin(straight, 1)[0], "Очистка истории изменила следующее вращение.")

    return {
        "session_autosave.json": normalize(final_autosave),
        "history.txt": normalize(txt_path.read_text(encoding="utf-8")),
        "history.csv": normalize(csv_bytes.decode("utf-8-sig")),
        "history.json": normalize(json_path.read_text(encoding="utf-8")),
        "export_summary.txt": normalize(summary),
    }


# --------------------------------------------------------------------------
# 4. Записанные файлы сохранения из examples/input и испорченные файлы
# --------------------------------------------------------------------------

def check_saved_files(tmp: Path) -> dict[str, str]:
    report: dict[str, object] = {}

    for name in ("session_v1.json", "session_v0_legacy.json"):
        source = INPUT_DIR / name
        before = source.read_bytes()
        session = read_session(source)
        loaded = state_of(session)
        engine = WheelEngine(session)
        # Обе записанные сессии — в режиме «удалять выпавший вариант», осталось по 2 варианта.
        report[name] = {"loaded": loaded, "next_winners": spin(engine, 2)}
        check(engine.session.active_ids == [], f"{name}: после двух вращений колесо должно опустеть.")
        check(source.read_bytes() == before, f"Загрузка изменила файл {name}.")

    original = json.loads((INPUT_DIR / "session_v1.json").read_text(encoding="utf-8"))
    original.pop("updated_at")
    check(report["session_v1.json"]["loaded"] == original, "session_v1.json после загрузки отличается от записанного.")

    # Незнакомые поля не мешают загрузке.
    extra = dict(original, updated_at="2026-01-01T00:00:00", future_field={"любое": "значение"})
    extra_path = tmp / "с лишним полем.json"
    extra_path.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
    check(state_of(read_session(extra_path)) == original, "Незнакомое поле в файле сохранения сломало загрузку.")

    # Испорченные и чужие файлы: только читаемая русская ошибка.
    broken_dir = tmp / "испорченные файлы"
    broken_dir.mkdir()

    def variant(**changes: object) -> str:
        return json.dumps({**original, **changes}, ensure_ascii=False)

    generated = {
        "пустой файл.json": b"",
        "не текст.json": b"\xff\xfe\x00\x01PK\x03\x04",
        "корень список.json": b"[1, 2, 3]",
        "число NaN.json": variant().replace('"value": 10.0', '"value": NaN').encode("utf-8"),
        "нет вариантов.json": variant(items=[]).encode("utf-8"),
        "active_ids чужой.json": variant(active_ids=[1, 99]).encode("utf-8"),
        "режим неизвестен.json": variant(options={"mode": "turbo"}).encode("utf-8"),
        "версия строкой.json": variant(contract_version="1").encode("utf-8"),
        "история не список.json": variant(history="нет").encode("utf-8"),
    }
    cases = [INPUT_DIR / "save_broken_truncated.json", INPUT_DIR / "save_foreign.json", INPUT_DIR / "save_newer_version.json"]
    for name, payload in generated.items():
        path = broken_dir / name
        path.write_bytes(payload)
        cases.append(path)
    cases.append(broken_dir / "такого файла нет.json")

    errors = {}
    for path in cases:
        before = path.read_bytes() if path.exists() else None
        try:
            read_session(path)
        except SessionFormatError as exc:
            message = str(exc).replace(str(broken_dir), "<TMP>").replace("\\", "/")
        except Exception as exc:  # noqa: BLE001 - именно это и проверяем
            raise SmokeFailure(f"{path.name}: вместо читаемой ошибки получено {type(exc).__name__}: {exc}") from exc
        else:
            raise SmokeFailure(f"{path.name}: испорченный/чужой файл загрузился без ошибки.")
        check(bool(re.search("[А-Яа-я]", message)), f"{path.name}: сообщение об ошибке не по-русски: {message}")
        check((path.read_bytes() if path.exists() else None) == before, f"{path.name}: файл изменён при неудачной загрузке.")
        errors[path.name] = message
    report["load_errors"] = errors

    return {"saved_files.json": dump(report)}


# --------------------------------------------------------------------------
# 5. Запуск без PySide6 и статическая проверка GUI-файлов
# --------------------------------------------------------------------------

def check_gui_boundary() -> dict[str, str]:
    check(
        not any(name == "PySide6" or name.startswith("PySide6.") for name in sys.modules),
        "Слои app/domain и app/storage не должны импортировать PySide6.",
    )
    for path in sorted((PROJECT_ROOT / "app" / "ui").glob("*.py")) + [PROJECT_ROOT / "main.py"]:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            raise SmokeFailure(f"Синтаксическая ошибка в {path.name}: {exc}") from exc

    # main.py без PySide6: понятное сообщение и код 1 вместо traceback.
    spec = importlib.util.spec_from_file_location("random_wheel_app_main", PROJECT_ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = {name: sys.modules[name] for name in list(sys.modules) if name == "PySide6" or name.startswith("PySide6.")}
    for name in saved:
        del sys.modules[name]
    sys.modules["PySide6"] = None  # имитация отсутствующей библиотеки
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            code = module.main()
    finally:
        del sys.modules["PySide6"]
        sys.modules.update(saved)
    message = stderr.getvalue()
    check(code == 1, f"main.py без PySide6 должен завершаться с кодом 1, получено {code!r}.")
    check("PySide6" in message and "pip install -r" in message and "Traceback" not in message,
          f"main.py без PySide6 должен печатать команду установки, получено: {message!r}")
    check(not any(name.startswith("app.ui") for name in sys.modules), "Проверка не должна импортировать GUI-слой.")
    return {}


# --------------------------------------------------------------------------

def compare(actual: dict[str, str]) -> None:
    expected_names = sorted(p.name for p in EXPECTED_DIR.iterdir() if p.is_file()) if EXPECTED_DIR.is_dir() else []
    problems = []
    for name in sorted(set(actual) | set(expected_names)):
        if name not in actual:
            problems.append(f"Лишний эталон, который тест не производит: examples/output_expected/{name}")
            continue
        if name not in expected_names:
            problems.append(f"Нет эталона examples/output_expected/{name}")
            continue
        expected = normalize((EXPECTED_DIR / name).read_text(encoding="utf-8"))
        if expected != actual[name]:
            diff = list(difflib.unified_diff(
                expected.splitlines(), actual[name].splitlines(),
                f"ожидалось: examples/output_expected/{name}", "получено", lineterm="", n=1,
            ))
            problems.append("\n".join([f"Результат отличается от эталона {name}:"] + diff[:40]))
    if problems:
        raise SmokeFailure("\n".join(problems))


def run(update: bool) -> None:
    home_autosave = autosave.AUTOSAVE_PATH
    home_before = file_fingerprint(home_autosave)
    capsule_before = capsule_listing()

    actual: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="random_wheel_smoke_") as raw_tmp:
        tmp = Path(raw_tmp)
        actual.update(check_parser(tmp))
        actual.update(check_wheel())
        actual.update(check_session(tmp))
        actual.update(check_saved_files(tmp))
        actual.update(check_gui_boundary())
    actual = {name: normalize(text) for name, text in actual.items()}

    if update:
        EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
        for name, text in actual.items():
            (EXPECTED_DIR / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"Эталоны обновлены: {EXPECTED_DIR}")
        return

    compare(actual)
    check(file_fingerprint(home_autosave) == home_before, f"Тест изменил пользовательский autosave: {home_autosave}")
    check(capsule_listing() == capsule_before, "Тест изменил файлы внутри капсулы (должен писать только во временный каталог).")


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")
    update = "--update-expected" in argv
    unknown = [arg for arg in argv if arg != "--update-expected"]
    if unknown:
        print(f"Неизвестный аргумент: {unknown[0]}. Допустим только --update-expected.", file=sys.stderr)
        return 2
    try:
        run(update)
    except SmokeFailure as exc:
        print(f"{TOOL_ID} smoke FAILED:\n{exc}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001
        print(f"{TOOL_ID} smoke FAILED: непредвиденная ошибка\n{traceback.format_exc()}", file=sys.stderr)
        return 1
    if update:
        return 0
    print(f"Python {sys.version_info.major}.{sys.version_info.minor}: разбор TXT, колесо с seed, autosave/загрузка, история, экспорт, испорченные файлы — совпадают с эталоном.")
    print("GUI-слой (app/ui, PySide6) не проверялся: окна не запускались, проверены только синтаксис и сообщение об отсутствии PySide6.")
    print(f"{TOOL_ID} smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
