"""Smoke- и регрессионный тест капсулы anime_rerank_tournament.

Проверяет слои app/domain, app/storage и app/utils на записанных примерах:
короткие сценарные сессии (выборы, пропуск, отмена, autosave -> загрузка),
оба режима оценивания, экспорт и формат файла сохранения.

GUI (app/ui, PySide6) здесь НЕ запускается: проверяется только синтаксис его файлов.
Тест пишет только во временную папку; нужна только стандартная библиотека.

Входы:   examples/input/ (два списка и два записанных файла сохранения).
Эталоны: examples/output_expected/.
Запуск:  python3 scripts/smoke_test.py
Новые эталоны: python3 scripts/smoke_test.py --write-expected ПАПКА_ВНЕ_КАПСУЛЫ
         (записывает свежие результаты в указанную папку, капсулу не трогает).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import difflib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.export import (  # noqa: E402
    export_matches_json,
    export_ranking_csv,
    export_ranking_json,
    export_ranking_txt,
    export_summary,
)
from app.domain.models import TournamentState  # noqa: E402
from app.domain.parser import parse_title_file  # noqa: E402
from app.domain.ranking import build_ranking  # noqa: E402
from app.domain.scoring import apply_scores  # noqa: E402
from app.domain.scoring_hard import hard_scores_for_size  # noqa: E402
from app.domain.scoring_light import light_distribution  # noqa: E402
from app.domain.tournament import TournamentEngine  # noqa: E402
from app.storage import autosave  # noqa: E402
from app.storage.save_load import load_state, save_state  # noqa: E402
from app.utils.errors import SaveFileError, TournamentError  # noqa: E402

TOOL_ID = "anime_rerank_tournament"
EXAMPLES = ROOT / "examples"
EXPECTED = EXAMPLES / "output_expected"
SAMPLE_INPUT = EXAMPLES / "input" / "sample_input.txt"
EDGE_INPUT = EXAMPLES / "input" / "список с пробелами и кириллицей.txt"
SAVE_V1 = EXAMPLES / "input" / "session_v1.json"
SAVE_LEGACY = EXAMPLES / "input" / "session_v0_legacy.json"

# Сценарии: L/R — выбрать левую/правую карточку, S — пропустить пару, U — отменить выбор,
# SAVE — прочитать autosave и продолжить с загруженного состояния (как после перезапуска).
SCENARIOS = [
    ("sample_light", SAMPLE_INPUT, "light", 42, "L R U L S R SAVE L U U R L R SAVE R L U R SAVE R"),
    ("sample_hard", SAMPLE_INPUT, "hard", 7, "R R SAVE L U R S S L U U L R L SAVE L R U SAVE U R L R"),
    ("edge_light", EDGE_INPUT, "light", 2024, "L SAVE R R U L S L U SAVE R L R"),
    ("edge_hard", EDGE_INPUT, "hard", 2024, "R U R L SAVE L R U U SAVE R L L R"),
]
# Записанные сохранения сделаны на EDGE_INPUT (hard, seed 314) после выборов "R L".
SAVED_SESSION = ("saved_session", "hard", 314, "R L", "U R S L SAVE R U L R L")
SCORING_SIZES = [1, 2, 3, 7, 9, 10, 11, 20, 21, 49, 50, 87, 100, 101, 250, 1000, 1001, 1049, 1050, 2000]
TIME_KEYS = {"created_at", "updated_at", "resolved_at"}


class SmokeFailure(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def half_up(numerator: int, denominator: int) -> int:
    """Целочисленное округление «0.5 вверх», независимое от кода капсулы."""
    return (2 * numerator + denominator) // (2 * denominator)


def normalize(value, ids: dict | None = None):
    """Убирает то, что нестабильно по своей природе: метки времени и uuid матчей."""
    ids = {} if ids is None else ids
    if isinstance(value, list):
        return [normalize(item, ids) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in TIME_KEYS:
                result[key] = "<time>" if item else item
            elif key == "id" and "left_id" in value:
                result[key] = ids.setdefault(item, f"match-{len(ids) + 1}")
            else:
                result[key] = normalize(item, ids)
        return result
    return value


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def clean_text(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip("\n") + "\n"


def core(state: TournamentState) -> dict:
    data = state.to_dict(include_undo=False)
    data.pop("updated_at")
    return data


def parsed_to_data(parsed) -> dict:
    return {
        "items": [item.to_dict() for item in parsed.items],
        "issues": [{"line_number": i.line_number, "text": i.text, "message": i.message} for i in parsed.issues],
        "stats": parsed.stats(),
    }


def run_script(engine: TournamentEngine, script: str, with_autosave: bool, name: str) -> TournamentEngine:
    """Проигрывает сценарий так же, как это делает GUI: autosave после каждого действия."""
    try:
        return _run_script(engine, script, with_autosave)
    except SmokeFailure as exc:
        raise SmokeFailure(f"{name}: {exc}") from None


def _run_script(engine: TournamentEngine, script: str, with_autosave: bool) -> TournamentEngine:
    history: list[dict] = []
    for step, token in enumerate(script.split(), start=1):
        where = f"шаг {step} ({token})"
        if token in ("L", "R"):
            check(engine.current_match() is not None, f"{where}: нет активного матча, сценарий длиннее турнира")
            history.append(core(engine.state))
            engine.select_left() if token == "L" else engine.select_right()
        elif token == "S":
            engine.skip_current_match()
        elif token == "U":
            check(engine.undo_last_action(), f"{where}: отменять нечего")
            if history:  # выборы, сделанные до начала сценария (записанное сохранение), сравнить не с чем
                check(core(engine.state) == history.pop(), f"{where}: после отмены состояние не равно состоянию до выбора")
        elif token == "SAVE":
            if with_autosave:
                loaded = autosave.read_autosave()
                check(loaded.to_dict() == engine.state.to_dict(), f"{where}: autosave после загрузки отличается от состояния")
                engine = TournamentEngine.from_state(loaded)
            continue
        else:
            raise SmokeFailure(f"неизвестная команда сценария: {token}")
        if with_autosave:
            autosave.write_autosave(engine.state)
    check(engine.is_finished(), "сценарий закончился, а турнир не завершён")
    return engine


def check_light_rules(n: int, scores: list[int]) -> None:
    """Правила docs/scoring_rules.md, лайтовый режим."""
    t1 = half_up(n, 100)
    t10 = max(t1, half_up(n * 10, 100))
    t20 = max(t10, half_up(n * 20, 100))
    t40 = max(t20, half_up(n * 40, 100))
    rest = n - t40
    expected = [10] * t1 + [9] * (t10 - t1) + [8] * (t20 - t10) + [7] * (t40 - t20)
    expected += [6] * ((rest + 1) // 2) + [5] * (rest // 2)
    check(scores == expected, f"light, N={n}: оценки не соответствуют docs/scoring_rules.md: {scores} != {expected}")
    check(scores == sorted(scores, reverse=True), f"light, N={n}: оценки не убывают вместе с местом")


def check_hard_rules(n: int, scores: list[int]) -> None:
    """Правила docs/scoring_rules.md, хардовый режим."""
    upper = (n + 1) // 2
    expected: list[int] = []
    for index in range(n):
        from_bottom = n - index  # 1 = последнее место
        ones = min(10, n)
        twos = half_up(n, 100)
        threes = half_up(n * 5, 100)
        if from_bottom <= ones:
            expected.append(1)
        elif index >= upper:
            expected.append(2 if from_bottom <= ones + twos else 3 if from_bottom <= ones + twos + threes else 4)
        else:
            expected.append(5 if index >= upper - upper // 2 else 6)
    elite = min(max(half_up(n, 100), 10), upper)
    if n <= 100:
        top = [8, 7, 7, 7, 7]
    elif n <= 1000:
        top = [9, 8, 8, 7, 7]
    elif elite == 10:
        top = [9, 9, 9, 8, 8, 8, 8, 8, 8, 7]
    else:
        top = [9, 9, 9] + [8] * 7 + [7] * (elite - 10)
    top = (top + [6] * elite)[:elite]
    expected[:elite] = top
    check(scores == expected, f"hard, N={n}: оценки не соответствуют docs/scoring_rules.md: {scores} != {expected}")
    check(10 not in scores, f"hard, N={n}: в хардовом режиме появилась оценка 10")
    check(scores == sorted(scores, reverse=True), f"hard, N={n}: оценки не убывают вместе с местом")
    if n >= 1001:
        check(7 in scores, f"hard, N={n}: оценка 7 не существует")


def check_ranking(state: TournamentState, ranking: list, mode: str, name: str) -> None:
    n = len(state.items)
    check([r.rank for r in ranking] == list(range(1, n + 1)), f"{name}: места не идут подряд от 1 до {n}")
    check(sorted(r.item.id for r in ranking) == sorted(i.id for i in state.items), f"{name}: в рейтинге не все тайтлы")
    check(ranking[0].item.id == state.active_ids[0], f"{name}: первое место занял не победитель турнира")
    check(ranking[0].item.losses == 0 and ranking[0].lost_to_title is None, f"{name}: у победителя есть поражение")
    user_matches = [m for m in state.completed_matches if not m.is_bye]
    check(len(user_matches) == n - 1, f"{name}: сыграно {len(user_matches)} матчей вместо {n - 1}")
    rounds = [r.item.eliminated_round for r in ranking[1:]]
    check(all(r is not None for r in rounds), f"{name}: проигравший без раунда выбывания")
    check(rounds == sorted(rounds, reverse=True), f"{name}: выбывший раньше стоит выше выбывшего позже")
    for ranked in ranking[1:]:
        check(ranked.item.losses == 1 and ranked.lost_to_title, f"{name}: не объяснено место «{ranked.item.title}»")
    scores = [r.item.new_score for r in ranking]
    (check_hard_rules if mode == "hard" else check_light_rules)(n, scores)


def export_all(state: TournamentState, ranking: list, out_dir: Path) -> dict[str, str]:
    """Пишет все экспорты во временную папку и возвращает их в виде, пригодном для сравнения."""
    out_dir.mkdir(parents=True, exist_ok=True)
    export_ranking_txt(out_dir / "ranking.txt", ranking)
    export_ranking_csv(out_dir / "ranking.csv", ranking)
    export_ranking_json(out_dir / "ranking.json", ranking)
    export_matches_json(out_dir / "matches.json", state.completed_matches)
    csv_bytes = (out_dir / "ranking.csv").read_bytes()
    check(csv_bytes.startswith(b"\xef\xbb\xbf"), "CSV-экспорт должен начинаться с UTF-8 BOM")
    check(csv_bytes.count(b"\r\n") >= len(ranking) + 1, "строки CSV-экспорта должны заканчиваться CRLF")
    ranking_json = json.loads((out_dir / "ranking.json").read_text(encoding="utf-8"))
    matches_json = json.loads((out_dir / "matches.json").read_text(encoding="utf-8"))
    for payload, kind in ((ranking_json, "ranking"), (matches_json, "matches")):
        check(payload.get("contract_version") == 1, f"{kind}.json: нет contract_version = 1")
        check(payload.get("kind") == f"{TOOL_ID}.{kind}", f"{kind}.json: неверное поле kind")
    return {
        "ranking.txt": clean_text((out_dir / "ranking.txt").read_text(encoding="utf-8")),
        "ranking.csv": clean_text(csv_bytes.decode("utf-8-sig")),
        "ranking.json": dump(ranking_json),
        "matches.json": dump(normalize(matches_json)),
    }


def finish_and_export(engine: TournamentEngine, name: str, tmp: Path) -> dict[str, str]:
    state = engine.state
    ranking = apply_scores(build_ranking(state), state.mode)
    check_ranking(state, ranking, state.mode, name)
    files = export_all(state, ranking, tmp / "экспорт с пробелами" / name)
    # Завершённый турнир с новыми оценками тоже должен переживать сохранение и загрузку.
    save_path = tmp / "сохранения" / f"{name} finished.json"
    save_state(save_path, state)
    reloaded = load_state(save_path)
    check(reloaded.to_dict() == state.to_dict(), f"{name}: завершённый турнир изменился после сохранения и загрузки")
    again = export_all(reloaded, apply_scores(build_ranking(reloaded), reloaded.mode), tmp / "повторный экспорт" / name)
    check(again == files, f"{name}: экспорт после загрузки сохранения отличается от экспорта до неё")
    return files


def check_engine_errors(items: list) -> None:
    engine = TournamentEngine.new(items, mode="light", random_seed=1)
    check(engine.undo_last_action() is False, "отмена в начале турнира должна возвращать False")
    for action, label in (
        (lambda: engine.select_winner(10**6), "выбор тайтла не из текущей пары"),
        (lambda: TournamentEngine.new([], random_seed=1), "турнир без тайтлов"),
    ):
        try:
            action()
        except TournamentError:
            continue
        raise SmokeFailure(f"ожидалась ошибка TournamentError: {label}")
    single = TournamentEngine.new(items[:1], random_seed=1)
    check(single.is_finished() and single.current_match() is None, "турнир из одного тайтла должен завершаться сразу")


def check_scenarios(tmp: Path) -> dict[str, str]:
    produced: dict[str, str] = {}
    parsed_by_input = {}
    for label, path in (("sample_input", SAMPLE_INPUT), ("edge_input", EDGE_INPUT)):
        parsed = parse_title_file(path)
        parsed_by_input[path] = parsed
        produced[f"{label}.parsed.json"] = dump(parsed_to_data(parsed))
        # Тот же текст в других кодировках и по пути с пробелами и кириллицей даёт тот же результат.
        text = path.read_text(encoding="utf-8")
        for encoding in ("utf-8-sig", "cp1251"):
            copy = tmp / "входные файлы" / f"{label} {encoding} копия.txt"
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(text.encode(encoding))
            check(
                parsed_to_data(parse_title_file(copy)) == parsed_to_data(parsed),
                f"{label}: разбор файла в кодировке {encoding} отличается от разбора UTF-8",
            )
    check_engine_errors(parsed_by_input[SAMPLE_INPUT].items)

    for name, path, mode, seed, script in SCENARIOS:
        items = parsed_by_input[path].items
        first = TournamentEngine.new(items, mode=mode, random_seed=seed)
        again = TournamentEngine.new(items, mode=mode, random_seed=seed)
        check(normalize(core(first.state)) == normalize(core(again.state)), f"{name}: один seed дал разные пары")
        autosave.write_autosave(first.state)
        check(autosave.has_autosave(), f"{name}: autosave не появился")
        saved = finish_and_export(run_script(first, script, True, name), name, tmp)
        plain = finish_and_export(run_script(again, script, False, name + " без autosave"), name + " без autosave", tmp)
        check(saved == plain, f"{name}: сессия с загрузкой autosave закончилась иначе, чем сессия без перезапуска")
        for file_name, text in saved.items():
            produced[f"{name}/{file_name}"] = text
    return produced


def check_saved_session(tmp: Path) -> dict[str, str]:
    name, mode, seed, prefix, script = SAVED_SESSION
    items = parse_title_file(EDGE_INPUT).items
    fresh = TournamentEngine.new(items, mode=mode, random_seed=seed)
    fresh_start = normalize(core(fresh.state))

    # Записанный файл формата 1: читается, совпадает с повторением тех же выборов и пишется обратно без изменений.
    v1_text = SAVE_V1.read_text(encoding="utf-8")
    v1 = load_state(SAVE_V1)
    check(json.loads(v1_text).get("contract_version") == 1, "session_v1.json: нет contract_version = 1")
    for token in prefix.split():
        fresh.select_left() if token == "L" else fresh.select_right()
    check(normalize(core(fresh.state)) == normalize(core(v1)), "session_v1.json не совпадает с повторением тех же выборов")
    rewritten = tmp / "сохранения" / "session_v1 rewritten.json"
    save_state(rewritten, v1)
    check(
        clean_text(rewritten.read_text(encoding="utf-8")) == clean_text(v1_text),
        "формат сохранения изменился: session_v1.json после загрузки и записи отличается от записанного файла",
    )
    check(not rewritten.with_name(rewritten.name + ".tmp").exists(), "после сохранения остался временный файл .tmp")

    # Сохранение версии 0.1.0 (без contract_version): читается и после отмен ведёт себя как формат 1.
    check("contract_version" not in json.loads(SAVE_LEGACY.read_text(encoding="utf-8")), "session_v0_legacy.json уже содержит версию")
    engines = [TournamentEngine.from_state(load_state(p)) for p in (SAVE_V1, SAVE_LEGACY)]
    check(normalize(core(engines[0].state)) == normalize(core(engines[1].state)), "сохранение 0.1.0 прочитано иначе, чем формат 1")
    for step in range(len(prefix.split())):
        for engine in engines:
            check(engine.undo_last_action(), f"записанное сохранение: отмена {step + 1} не сработала")
        check(
            normalize(core(engines[0].state)) == normalize(core(engines[1].state)),
            f"после отмены {step + 1} сохранение 0.1.0 расходится с форматом 1",
        )
    check(normalize(core(engines[0].state)) == fresh_start, "отмена всех выборов не вернула турнир к начальному состоянию")

    results = []
    for path in (SAVE_V1, SAVE_LEGACY):
        engine = TournamentEngine.from_state(load_state(path))
        autosave.write_autosave(engine.state)
        label = f"{name} {path.stem}"
        results.append(finish_and_export(run_script(engine, script, True, label), label, tmp))
    check(results[0] == results[1], "продолжение сохранения 0.1.0 дало другой результат, чем продолжение формата 1")
    return {f"{name}/{file_name}": text for file_name, text in results[0].items()}


def check_bad_saves(tmp: Path) -> None:
    """Повреждённый, чужой или слишком новый файл — понятная ошибка по-русски, файл не меняется."""
    good = json.loads(SAVE_V1.read_text(encoding="utf-8"))
    good_text = json.dumps(good, ensure_ascii=False, indent=2)

    def changed(**fields) -> str:
        return json.dumps({**good, **fields}, ensure_ascii=False)

    ranking_export = tmp / "экспорт с пробелами" / "edge_hard" / "ranking.json"
    cases = {
        "пустой файл": b"",
        "обрезанный файл": good_text[: len(good_text) // 2].encode("utf-8"),
        "не UTF-8": b"\xff\xfe\x00\x01 not a save",
        "JSON-массив": b"[]",
        "пустой объект": b"{}",
        "чужой тип файла": json.dumps({"kind": "random_wheel_app.save", "items": []}).encode("utf-8"),
        "экспорт рейтинга вместо сохранения": ranking_export.read_bytes(),
        "более новая версия формата": changed(contract_version=2).encode("utf-8"),
        "версия формата строкой": changed(contract_version="1").encode("utf-8"),
        "нет тайтлов": changed(items=[]).encode("utf-8"),
        "тайтл без id": changed(items=[{"title": "без id"}]).encode("utf-8"),
        "неизвестный режим": changed(mode="medium").encode("utf-8"),
        "ссылка на несуществующий тайтл": changed(active_ids=[1, 2, 999]).encode("utf-8"),
        "списки не сходятся с историей": changed(eliminated_ids=[]).encode("utf-8"),
        "нет открытого матча": changed(current_matches=[]).encode("utf-8"),
        "тайтл дважды в раунде": changed(active_ids=good["active_ids"] + good["active_ids"][:1]).encode("utf-8"),
        "испорченный шаг отмены": changed(undo_stack=["мусор"]).encode("utf-8"),
    }
    folder = tmp / "плохие сохранения"
    folder.mkdir()
    for label, payload in cases.items():
        path = folder / f"{label}.json"
        path.write_bytes(payload)
        try:
            load_state(path)
        except SaveFileError as exc:
            message = str(exc)
        except Exception as exc:  # noqa: BLE001 - любая другая ошибка здесь и есть провал теста
            raise SmokeFailure(f"плохое сохранение «{label}»: вместо понятной ошибки {type(exc).__name__}: {exc}")
        else:
            raise SmokeFailure(f"плохое сохранение «{label}» загрузилось без ошибки")
        check(str(path) in message, f"плохое сохранение «{label}»: в сообщении нет пути к файлу")
        check(any("а" <= ch <= "я" for ch in message), f"плохое сохранение «{label}»: сообщение не по-русски")
        check(path.read_bytes() == payload, f"плохое сохранение «{label}»: файл изменён при чтении")
    check("более новой версией" in _error_text(folder / "более новая версия формата.json"), "нет объяснения про новую версию формата")
    check("не найден" in _error_text(folder / "такого файла нет.json"), "нет объяснения про отсутствующий файл")

    # То же через autosave: повреждённый autosave не должен молча превращаться в пустой турнир.
    autosave.autosave_path().write_bytes(cases["обрезанный файл"])
    try:
        autosave.read_autosave()
    except SaveFileError:
        pass
    else:
        raise SmokeFailure("повреждённый autosave загрузился без ошибки")
    autosave.clear_autosave()
    check(not autosave.has_autosave(), "clear_autosave не удалил autosave")


def _error_text(path: Path) -> str:
    try:
        load_state(path)
    except SaveFileError as exc:
        return str(exc)
    return ""


def check_scoring_tables() -> dict[str, str]:
    for n in list(range(1, 1301)) + [1999, 2000, 4950, 5000, 10001]:
        distribution = light_distribution(n)
        check(sum(distribution.values()) == n, f"light, N={n}: сумма распределения не равна N")
        check_light_rules(n, [score for score in (10, 9, 8, 7, 6, 5) for _ in range(distribution[score])])
        check_hard_rules(n, hard_scores_for_size(n))
    table = {"light": {}, "hard": {}}
    for n in SCORING_SIZES:
        table["light"][str(n)] = {str(k): v for k, v in light_distribution(n).items() if v}
        hard = hard_scores_for_size(n)
        table["hard"][str(n)] = {str(score): hard.count(score) for score in range(9, 0, -1) if score in hard}
    return {"scoring_distributions.json": dump(table)}


def check_without_pyside(tmp: Path) -> None:
    """Домен и хранение импортируются без PySide6, а main.py без неё даёт понятное сообщение."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    block = "import sys; sys.modules['PySide6'] = None; sys.path.insert(0, sys.argv[1]); "
    imports = block + (
        "import app.domain.export, app.domain.models, app.domain.parser, app.domain.ranking, app.domain.scoring, "
        "app.domain.scoring_hard, app.domain.scoring_light, app.domain.tournament, app.storage.autosave, "
        "app.storage.save_load, app.utils.errors, app.utils.rounding; print('imports ok')"
    )
    done = subprocess.run(
        [sys.executable, "-B", "-c", imports, str(ROOT)], cwd=tmp, env=env, capture_output=True, encoding="utf-8"
    )
    check(done.returncode == 0 and "imports ok" in done.stdout, f"слои domain/storage/utils требуют PySide6:\n{done.stderr}")
    launch = block + "import runpy; runpy.run_path(sys.argv[2], run_name='__main__')"
    done = subprocess.run(
        [sys.executable, "-B", "-c", launch, str(ROOT), str(ROOT / "main.py")],
        cwd=tmp, env=env, capture_output=True, encoding="utf-8",
    )
    check(done.returncode == 1, f"main.py без PySide6 должен завершаться с кодом 1, получен {done.returncode}")
    check("Traceback" not in done.stderr, f"main.py без PySide6 печатает traceback:\n{done.stderr}")
    check(
        "Не найдена библиотека PySide6" in done.stderr and "pip install" in done.stderr,
        f"main.py без PySide6 не объясняет, что установить:\n{done.stderr}",
    )
    for path in [ROOT / "main.py", *sorted((ROOT / "app" / "ui").glob("*.py"))]:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def compare_with_expected(produced: dict[str, str]) -> None:
    problems = []
    for rel, text in sorted(produced.items()):
        path = EXPECTED / rel
        if not path.is_file():
            problems.append(f"нет эталонного файла examples/output_expected/{rel}")
            continue
        expected = clean_text(path.read_text(encoding="utf-8"))
        if expected != text:
            diff = difflib.unified_diff(
                expected.splitlines(), text.splitlines(), f"эталон/{rel}", f"получено/{rel}", lineterm="", n=1
            )
            problems.append("\n".join(list(diff)[:24]))
    known = {p.relative_to(EXPECTED).as_posix() for p in EXPECTED.rglob("*") if p.is_file()}
    for rel in sorted(known - set(produced)):
        problems.append(f"лишний эталонный файл examples/output_expected/{rel}")
    check(not problems, "результат отличается от examples/output_expected:\n" + "\n".join(problems))


def capsule_listing() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*"))


def run(write_expected: Path | None) -> None:
    listing_before = capsule_listing()
    default_autosave = autosave.autosave_path()
    check(default_autosave == Path.home() / ".anime_rerank_tournament" / "autosave.json", "изменилось место autosave по умолчанию")
    check(ROOT not in default_autosave.parents, "autosave по умолчанию лежит внутри капсулы")
    real_before = default_autosave.stat().st_mtime_ns if default_autosave.exists() else None

    with tempfile.TemporaryDirectory(prefix="anime rerank проверка ") as raw_tmp:
        tmp = Path(raw_tmp)
        state_dir = tmp / "состояние программы"
        original_dir = autosave.autosave_dir
        autosave.autosave_dir = lambda: state_dir  # autosave теста живёт только во временной папке
        try:
            check(state_dir in autosave.autosave_path().parents, "не удалось перенаправить autosave во временную папку")
            produced = check_scenarios(tmp)
            produced.update(check_saved_session(tmp))
            check_bad_saves(tmp)
        finally:
            autosave.autosave_dir = original_dir
        produced.update(check_scoring_tables())
        check_without_pyside(tmp)
        summary = export_summary(tmp / "ranking.txt", 9, "Записано тайтлов")
        check(summary.startswith("Готово.") and "Результат: " in summary, "итоговое сообщение экспорта не по стандарту")

    if write_expected is not None:
        for rel, text in produced.items():
            target = write_expected / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        print(f"Эталоны записаны: {write_expected} (файлов: {len(produced)}). Сравнение не выполнялось.")
    else:
        compare_with_expected(produced)

    real_after = default_autosave.stat().st_mtime_ns if default_autosave.exists() else None
    check(real_before == real_after, "тест изменил настоящий autosave пользователя")
    check(capsule_listing() == listing_before, "тест оставил файлы внутри капсулы")

    print(f"Сценарных сессий: {len(SCENARIOS) + 2} (light и hard; выбор, пропуск, отмена, autosave и загрузка, экспорт)")
    print("Записанные сохранения: формат 1 и сохранение версии 0.1.0 прочитаны и продолжены")
    print(f"Сравнено с эталонами examples/output_expected: {len(produced)} файлов")
    print("GUI (app/ui, PySide6) не запускался: проверены только синтаксис его файлов и сообщение об отсутствии PySide6")


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    write_expected = None
    if len(argv) == 2 and argv[0] == "--write-expected":
        write_expected = Path(argv[1]).resolve()
        if write_expected == ROOT or ROOT in write_expected.parents:
            print("Папка для --write-expected должна быть вне капсулы: скопируйте эталоны вручную после просмотра.", file=sys.stderr)
            return 2
    elif argv:
        print("Использование: smoke_test.py [--write-expected ПАПКА_ВНЕ_КАПСУЛЫ]", file=sys.stderr)
        return 2
    try:
        run(write_expected)
    except SmokeFailure as exc:
        print(f"{TOOL_ID} smoke FAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - любая ошибка кода капсулы должна дать читаемый отказ
        print(f"{TOOL_ID} smoke FAILED: непредвиденная ошибка {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if write_expected is None:
        print(f"{TOOL_ID} smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
