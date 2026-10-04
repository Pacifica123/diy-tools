"""Smoke + регрессия капсулы mpl.

Запуск из любой папки: python3 /abs/path/tools/mpl/scripts/smoke_test.py
Пишет только во временную папку, сеть и PySide6 не нужны.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import configparser  # noqa: E402
import contextlib  # noqa: E402
import difflib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
INPUT_DIR = ROOT / "examples" / "input"
EXPECTED_DIR = ROOT / "examples" / "output_expected"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import mpl  # noqa: E402
from mpl.abi import ABI_VERSION, CONTRACT_VERSION, run_contract_json  # noqa: E402
from mpl.api import process_text  # noqa: E402
from mpl.cli import main as cli_main  # noqa: E402
from mpl.core.layout import build_layout  # noqa: E402
from mpl.core.parser import parse_mermaid  # noqa: E402


class SmokeFailure(Exception):
    pass


def check(condition: object, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def check_same_text(actual: str, expected: str, what: str) -> None:
    # Единственная нормализация: переводы строк в самом конце файла (их могут
    # добавить редактор или patch-инструмент). Всё остальное сравнивается целиком.
    actual, expected = actual.rstrip("\n"), expected.rstrip("\n")
    if actual == expected:
        return
    diff = list(
        difflib.unified_diff(expected.splitlines(), actual.splitlines(), "ожидалось", "получено", lineterm="", n=1)
    )
    shown = "\n".join(diff[:40])
    raise SmokeFailure(f"{what}: результат не совпал с эталоном\n{shown}")


# ---------------------------------------------------------------------------
# Инварианты раскладки на встроенных мини-диаграммах (были в smoke до 0.2.0).

SAMPLE = """flowchart LR
    A[Русский вход] -->|да| B{Проверка}
    B -- ок --> C((SVG))
    B -. warning .-> D[Отчёт]
"""

CYCLE_SAMPLE = """flowchart TD
    A[Старт] --> B[Проверка]
    B --> C[Исправление]
    C --> A
"""

GROUP_EDGE_SAMPLE = """flowchart TD
    ToolShelf[DIY tool shelf]
    subgraph MPL
    MplGui[Qt GUI]
    MplCore[core parser]
    MplGui --> MplCore
    end
    ToolShelf --> MPL
"""

FANOUT_SAMPLE = """flowchart TD
    ToolCapsule[tool capsule]
    ToolCapsule --> Readme[README.md]
    ToolCapsule --> ToolIni[tool.ini]
    ToolCapsule --> RunBat[run.bat]
    ToolCapsule --> RunSh[run.sh]
    ToolCapsule --> Src[src]
    ToolCapsule --> Examples[examples]
"""

EXTERNAL_REF_SAMPLE = """flowchart TD
    Outside[external node]
    subgraph G
    Inside[inside node]
    Inside --> Outside
    end
"""

TWO_GROUP_SAMPLE = """flowchart TD
    subgraph One
    A1[one a] --> A2[one b] --> A3[one c]
    end
    subgraph Two
    B1[two a] --> B2[two b]
    end
"""

CLUSTER_SAMPLE = """flowchart TD
    A[external start] --> B[external middle]
    subgraph G
    G1[group one] --> G2[group two] --> G3[group three]
    end
    B --> G
    G --> C[external finish]
    C --> A
"""


def _boxes_overlap(left, right) -> bool:
    return not (
        left.x + left.width <= right.x
        or right.x + right.width <= left.x
        or left.y + left.height <= right.y
        or right.y + right.height <= left.y
    )


def _box_contains(outer, inner) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and outer.x + outer.width >= inner.x + inner.width
        and outer.y + outer.height >= inner.y + inner.height
    )


def check_layout_invariants() -> None:
    result = process_text(SAMPLE, render=True)
    diagram = result["diagram"]
    check(result["ok"] is True, "process_text: ok должен быть true")
    check(len(diagram["nodes"]) == 4 and len(diagram["edges"]) == 3, f"SAMPLE: неверный разбор: {diagram}")
    for needle in ("Русский вход", "marker-end", "#ffffff", ".node-decision"):
        check(needle in result["svg"], f"SAMPLE: в SVG нет {needle!r}")

    cycle_svg = process_text(CYCLE_SAMPLE, render=True)["svg"]
    size = re.search(r'width="([0-9]+)" height="([0-9]+)"', cycle_svg)
    check(size is not None and int(size.group(1)) < 900 and int(size.group(2)) < 900, "цикл раздувает canvas")
    check(" C " not in cycle_svg, "рёбра должны быть ортогональными ломаными, а не кривыми")

    group_result = process_text(GROUP_EDGE_SAMPLE, render=True)
    group_svg = group_result["svg"]
    check(len(group_result["diagram"]["groups"]) == 1, "GROUP_EDGE: ожидалась одна группа")
    check(
        not any(node["id"] == "MPL" for node in group_result["diagram"]["nodes"]),
        "стрелка к subgraph по id не должна создавать одноимённый узел",
    )
    order = [group_svg.index(f'<g class="{name}">') for name in ("groups", "edges", "edge-labels", "nodes", "node-labels")]
    check(order == sorted(order), "нарушен порядок SVG-слоёв groups/edges/edge-labels/nodes/node-labels")

    fanout_svg = process_text(FANOUT_SAMPLE, render=True)["svg"]
    first_segment_x = re.findall(r"M ([0-9.]+) [0-9.]+ L \1", fanout_svg)
    check(len(set(first_segment_x)) >= 3, "fan-out: рёбра выходят из одного порта")
    fanout_size = re.search(r'width="([0-9]+)" height="([0-9]+)"', fanout_svg)
    check(fanout_size is not None and int(fanout_size.group(1)) < 1300, "fan-out: слишком широкий canvas")

    external_nodes = {node["id"]: node for node in parse_mermaid(EXTERNAL_REF_SAMPLE).to_dict()["nodes"]}
    check(external_nodes["Outside"]["group"] is None, "bare-ссылка из subgraph не должна затягивать внешний узел в группу")
    check(external_nodes["Inside"]["group"] == "G", "внутренний узел потерял группу")

    two_group_diagram = parse_mermaid(TWO_GROUP_SAMPLE)
    check(
        [node_id for node_id in two_group_diagram.nodes] == ["A1", "A2", "A3", "B1", "B2"] and len(two_group_diagram.edges) == 3,
        "цепочка A --> B --> C должна давать все узлы и по ребру на каждое звено",
    )
    group_boxes = list(build_layout(two_group_diagram).group_boxes.values())
    check(len(group_boxes) == 2 and not _boxes_overlap(group_boxes[0], group_boxes[1]), "top-level группы наложились")

    cluster_layout = build_layout(parse_mermaid(CLUSTER_SAMPLE))
    group_box = cluster_layout.group_boxes["G"]
    for node_id in ("A", "B", "C"):
        check(not _box_contains(group_box, cluster_layout.node_boxes[node_id]), f"рамка группы накрыла внешний узел {node_id}")
    for node_id in ("G1", "G2", "G3"):
        check(_box_contains(group_box, cluster_layout.node_boxes[node_id]), f"узел группы {node_id} вне рамки группы")
    check("-42.0" not in process_text(CLUSTER_SAMPLE, render=True)["svg"], "обратное ребро ушло в дальний side-lane")


# ---------------------------------------------------------------------------
# Регрессия: examples/input -> examples/output_expected через настоящий CLI.

def run_cli(argv: list[str], stdin_text: str | None = None) -> tuple[int, str, str]:
    """Вызов CLI в этом же процессе с перехватом stdout/stderr."""
    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    if stdin_text is not None:
        sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli_main(argv)
            except SystemExit as exc:  # argparse
                code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


def regression_cases() -> list[str]:
    names = sorted(path.stem for path in INPUT_DIR.glob("*.mmd"))
    check(len(names) >= 2, f"в {INPUT_DIR} нет регрессионных входов")
    known = set()
    for name in names:
        for suffix in (".ast.json", ".svg"):
            check((EXPECTED_DIR / (name + suffix)).is_file(), f"нет эталона examples/output_expected/{name}{suffix}")
            known.add(name + suffix)
        known.add(name + ".strict_error.json")
    orphans = sorted(path.name for path in EXPECTED_DIR.iterdir() if path.name not in known)
    check(not orphans, f"в examples/output_expected есть файлы без входа: {orphans}")
    return names


def expected_text(name: str, suffix: str) -> str:
    return (EXPECTED_DIR / (name + suffix)).read_text(encoding="utf-8")


def check_regression_in_process(names: list[str], tmp: Path) -> None:
    for name in names:
        source_path = INPUT_DIR / f"{name}.mmd"
        svg_path, ast_path = tmp / f"{name}.svg", tmp / f"{name}.ast.json"
        code, out, err = run_cli(["--input", str(source_path), "--svg", str(svg_path), "--ast", str(ast_path)])
        check(code == 0, f"{name}: CLI вернул {code}: {err}")
        check_same_text(ast_path.read_text(encoding="utf-8"), expected_text(name, ".ast.json"), f"{name}.ast.json")
        check_same_text(svg_path.read_text(encoding="utf-8"), expected_text(name, ".svg"), f"{name}.svg")

        # Итоговый отчёт (STANDARD §13) и audit output для флага G.
        for needle in ("Готово.", "Обработано: 1", "Создано: 2", "Ошибок: 0", f"Результат: {svg_path}", f"Отчёт: {ast_path}", "best-effort"):
            check(needle in out, f"{name}: в итоговом отчёте CLI нет {needle!r}")
        ast = json.loads(expected_text(name, ".ast.json"))
        check(ast.get("contract_version") == CONTRACT_VERSION, f"{name}: в AST нет contract_version")
        check(list(ast) == ["contract_version", "kind", "direction", "nodes", "edges", "groups", "warnings"], f"{name}: поля AST изменились")
        check(f"Предупреждений: {len(ast['warnings'])}" in out, f"{name}: отчёт не показал число предупреждений")
        for warning in ast["warnings"]:
            check(warning in out, f"{name}: предупреждение не попало в отчёт: {warning}")

        # --json: тот же AST и тот же SVG, плюс маркеры контракта; stdout — чистый JSON.
        code, out, err = run_cli(["--input", str(source_path), "--json"])
        check(code == 0, f"{name}: --json вернул {code}: {err}")
        result = json.loads(out)
        diagram = {key: value for key, value in ast.items() if key != "contract_version"}
        check(
            result
            == {
                "ok": True,
                "diagram": diagram,
                "warnings": ast["warnings"],
                "svg": expected_text(name, ".svg"),
                "abi": {"name": "mpl-json", "version": ABI_VERSION},
                "contract_version": CONTRACT_VERSION,
            },
            f"{name}: JSON-результат --json не соответствует контракту/эталону",
        )

        # ABI: source и input_path дают одно и то же; render=false убирает svg.
        text = source_path.read_text(encoding="utf-8")
        by_source = json.loads(run_contract_json(json.dumps({"source": text})))
        check(by_source == result, f"{name}: ABI source расходится с --json")
        code, out, err = run_cli(["--abi-json"], json.dumps({"input_path": str(source_path), "render": False}, ensure_ascii=False))
        check(code == 0, f"{name}: --abi-json вернул {code}: {err}")
        no_svg = dict(result)
        del no_svg["svg"]
        check(json.loads(out) == no_svg, f"{name}: ABI input_path/render=false расходится с --json")


def check_error_paths(names: list[str], tmp: Path) -> None:
    strict_cases = [name for name in names if (EXPECTED_DIR / f"{name}.strict_error.json").is_file()]
    check(strict_cases, "нет ни одного регрессионного входа с эталоном ошибки (*.strict_error.json)")
    for name in strict_cases:
        source_path = INPUT_DIR / f"{name}.mmd"
        expected = expected_text(name, ".strict_error.json")
        payload = json.dumps({"input_path": str(source_path), "strict": True}, ensure_ascii=False)
        code, out, err = run_cli(["--abi-json"], payload)
        check(code == 2, f"{name}: strict ABI должен вернуть код 2, вернул {code}")
        check_same_text(out, expected, f"{name}.strict_error.json")
        error = json.loads(out)
        check(error["ok"] is False and error["error"]["code"] == 2 and error["contract_version"] == CONTRACT_VERSION, f"{name}: плохой JSON ошибки")
        check(err.startswith("mpl: ошибка входа: ") and error["error"]["message"] in err, f"{name}: нет русского сообщения в stderr")

        svg_path = tmp / f"{name}.strict.svg"
        code, out, err = run_cli(["--input", str(source_path), "--strict", "--svg", str(svg_path)])
        check(code == 2 and out == "" and err.startswith("mpl: ошибка входа: "), f"{name}: --strict должен дать код 2 и сообщение, дал {code}")
        check(not svg_path.exists(), f"{name}: при ошибке --strict не должен создаваться SVG")

        ast_path = tmp / f"{name}.warn.ast.json"
        code, out, err = run_cli(["--input", str(source_path), "--fail-on-warning", "--ast", str(ast_path)])
        check(code == 3, f"{name}: --fail-on-warning должен вернуть 3, вернул {code}")
        check(ast_path.is_file() and "Предупреждений:" in out, f"{name}: --fail-on-warning должен всё равно записать отчёт")

    missing = tmp / path_name("нет такого файла.mmd", "no such file.mmd")
    code, out, err = run_cli(["--input", str(missing), "--svg", str(tmp / "never.svg")])
    check(code == 2 and out == "" and "mpl: ошибка входа" in err, "отсутствующий входной файл должен давать код 2")
    code, out, err = run_cli([])
    check(code == 2 and "укажи ровно один источник" in err, "запуск без источника должен давать код 2")
    for bad_payload in ("это не JSON", "[]", "{}"):
        code, out, err = run_cli(["--abi-json"], bad_payload)
        check(code == 2, f"ABI {bad_payload!r}: ожидался код 2, получен {code}")
        error = json.loads(out)
        check(error["ok"] is False and error["error"]["kind"] == "bad_input" and error["abi"]["name"] == "mpl-json", f"ABI {bad_payload!r}: плохой JSON ошибки")
    check("Traceback" not in err, "CLI не должен показывать traceback")


# ---------------------------------------------------------------------------
# Настоящие процессы: другая текущая папка, пробелы и кириллица в путях,
# другой PYTHONHASHSEED, UTF-8 в stdin/stdout, launcher.

def _cyrillic_paths_possible() -> bool:
    try:
        os.fsencode("кириллица")
    except UnicodeEncodeError:  # например LC_ALL=POSIX с отключённым UTF-8-режимом Python
        return False
    return True


CYRILLIC_PATHS = _cyrillic_paths_possible()


def path_name(russian: str, fallback: str) -> str:
    return russian if CYRILLIC_PATHS else fallback


def child_env(hash_seed: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = hash_seed
    return env


def run_process(command: list[str], cwd: Path, env: dict[str, str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=str(cwd), env=env, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)


def check_regression_subprocess(names: list[str], tmp: Path) -> None:
    work = tmp / path_name("рабочая папка с пробелами", "work dir with spaces")
    work.mkdir()
    main_py = str(ROOT / "main.py")
    for index, name in enumerate(names):
        local_name = path_name(f"моя схема {index}", f"my diagram {index}")
        shutil.copyfile(INPUT_DIR / f"{name}.mmd", work / f"{local_name}.mmd")
        done = run_process(
            [sys.executable, main_py, "--cli", "--input", f"{local_name}.mmd", "--svg", f"{local_name}.svg", "--ast", f"{local_name}.ast.json"],
            work,
            child_env(str(index + 1)),
        )
        check(done.returncode == 0, f"{name}: процесс CLI вернул {done.returncode}: {done.stderr.decode('utf-8', 'replace')}")
        check(done.stdout.decode("utf-8").startswith("Готово."), f"{name}: stdout процесса не UTF-8-отчёт")
        check_same_text((work / f"{local_name}.ast.json").read_text(encoding="utf-8"), expected_text(name, ".ast.json"), f"{name}.ast.json (процесс, относительные пути)")
        check_same_text((work / f"{local_name}.svg").read_text(encoding="utf-8"), expected_text(name, ".svg"), f"{name}.svg (процесс, относительные пути)")

    # ABI через настоящие stdin/stdout: UTF-8 независимо от локали.
    name = names[0]
    payload = json.dumps({"input_path": path_name("моя схема 0.mmd", "my diagram 0.mmd"), "render": True}, ensure_ascii=False).encode("utf-8")
    done = run_process([sys.executable, main_py, "--cli", "--abi-json"], work, child_env("0"), payload)
    check(done.returncode == 0, f"ABI-процесс вернул {done.returncode}: {done.stderr.decode('utf-8', 'replace')}")
    result = json.loads(done.stdout.decode("utf-8"))
    check(result["svg"] == expected_text(name, ".svg") and result["contract_version"] == CONTRACT_VERSION, "ABI-процесс: результат не совпал с эталоном")


def check_launchers(names: list[str], tmp: Path) -> str:
    bat = (ROOT / "run.bat").read_text(encoding="utf-8")
    sh = (ROOT / "run.sh").read_text(encoding="utf-8")
    check("%~dp0main.py" in bat and not re.search(r"^\s*cd\b", bat, re.MULTILINE | re.IGNORECASE), "run.bat не должен делать cd и должен звать main.py по полному пути")
    check('"$DIR/main.py"' in sh and not re.search(r"^\s*cd\b", sh, re.MULTILINE), "run.sh не должен делать cd и должен звать main.py по полному пути")

    shell = shutil.which("sh") if os.name == "posix" else None
    python3 = shutil.which("python3")
    if shell is None or python3 is None:
        return "launcher run.sh не запускался (нет sh/python3 в PATH); run.bat проверен только по тексту"
    probe = subprocess.run([python3, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"], timeout=120)
    if probe.returncode != 0:
        return "launcher run.sh не запускался (python3 из PATH старше 3.11); run.bat проверен только по тексту"
    work = tmp / path_name("запуск через launcher", "launcher run")
    work.mkdir()
    name = names[-1]
    source, svg, ast = path_name("вход.mmd", "in.mmd"), path_name("выход.svg", "out.svg"), path_name("выход.ast.json", "out.ast.json")
    shutil.copyfile(INPUT_DIR / f"{name}.mmd", work / source)
    done = run_process([shell, str(ROOT / "run.sh"), "--cli", "--input", source, "--svg", svg, "--ast", ast], work, child_env("5"))
    check(done.returncode == 0, f"run.sh вернул {done.returncode}: {done.stderr.decode('utf-8', 'replace')}")
    check_same_text((work / svg).read_text(encoding="utf-8"), expected_text(name, ".svg"), f"{name}.svg (run.sh, относительные пути)")
    check_same_text((work / ast).read_text(encoding="utf-8"), expected_text(name, ".ast.json"), f"{name}.ast.json (run.sh, относительные пути)")
    return "launcher run.sh запущен из чужой папки с относительными путями; run.bat проверен только по тексту"


def check_gui_layer(tmp: Path) -> str:
    # Модуль GUI обязан импортироваться без Qt: сам Qt подключается только в main().
    from mpl.gui import qt_app

    check(qt_app._read_svg_size('<svg xmlns="x" width="463" height="664">') == (463, 664), "gui: _read_svg_size сломан")
    has_qt = any(importlib.util.find_spec(binding) is not None for binding in ("PySide6", "PyQt6"))
    if has_qt:
        return "GUI-слой НЕ проверялся: Qt установлен, но smoke не открывает окна (ручная проверка: python main.py)"
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = qt_app.main(["mpl"])
    check(code == 5 and "mpl GUI требует PySide6 или PyQt6" in err.getvalue(), "без Qt запуск GUI должен дать код 5 и русское сообщение")
    done = run_process([sys.executable, str(ROOT / "main.py")], tmp, child_env("0"))
    check(done.returncode == 5 and b"Traceback" not in done.stderr and done.stdout == b"", f"python main.py без Qt: ожидался код 5 без traceback, получен {done.returncode}")
    return "GUI-слой НЕ проверялся: PySide6/PyQt6 не установлены (проверено только понятное сообщение и код 5)"


def check_passport() -> None:
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(ROOT / "tool.ini", encoding="utf-8")
    check(ini["tool"]["version"] == mpl.__version__, f"tool.ini version={ini['tool']['version']} != mpl.__version__={mpl.__version__}")
    check(ini["data"]["contract_version"] == str(CONTRACT_VERSION), "tool.ini contract_version расходится с кодом")
    for key in ("contract_doc", "input_contract", "output_contract"):
        target = ini["data"][key].split("#")[0]
        check((ROOT / target).is_file(), f"tool.ini [data] {key}: нет файла {target}")
    check((ROOT / ini["checks"]["regression"]).is_dir(), "tool.ini [checks] regression: нет такой папки")
    check((ROOT / ini["tool"]["changelog"]).is_file(), "tool.ini [tool] changelog: нет файла")
    contract = (ROOT / "docs" / "CONTRACT.md").read_text(encoding="utf-8")
    abi_doc = (ROOT / "docs" / "ABI.md").read_text(encoding="utf-8")
    check(f"Версия контракта: {CONTRACT_VERSION}" in contract and "ABI.md" in contract, "docs/CONTRACT.md: нет версии контракта или ссылки на ABI.md")
    check(f"mpl-json {ABI_VERSION}" in abi_doc and f'"contract_version": {CONTRACT_VERSION}' in abi_doc, "docs/ABI.md: версии расходятся с кодом")
    check(f"## {mpl.__version__}" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), "CHANGELOG.md: нет записи о текущей версии")


def pycache_dirs() -> set[Path]:
    return {path for path in ROOT.rglob("__pycache__")}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    pycache_before = pycache_dirs()
    notes: list[str] = []
    try:
        check_passport()
        check_layout_invariants()
        names = regression_cases()
        with tempfile.TemporaryDirectory(prefix="mpl smoke ") as tmp_dir:
            tmp = Path(tmp_dir)
            in_process = tmp / "in process"
            in_process.mkdir()
            check_regression_in_process(names, in_process)
            check_error_paths(names, in_process)
            check_regression_subprocess(names, tmp)
            notes.append(check_launchers(names, tmp))
            notes.append(check_gui_layer(tmp))
        if not CYRILLIC_PATHS:
            notes.append("кириллица в создаваемых путях НЕ проверялась: файловая кодировка этого запуска Python её не кодирует")
        created = sorted(str(path.relative_to(ROOT)) for path in pycache_dirs() - pycache_before)
        check(not created, f"smoke оставил __pycache__ в капсуле: {created}")
    except SmokeFailure as failure:
        print(f"mpl smoke FAILED: {failure}", file=sys.stderr)
        return 1
    print(f"Регрессия: {len(names)} входов из examples/input совпали с examples/output_expected (AST JSON и SVG целиком).")
    print(f"Python {sys.version_info.major}.{sys.version_info.minor}, контракт {CONTRACT_VERSION} (mpl-json {ABI_VERSION}).")
    for note in notes:
        print(f"Примечание: {note}.")
    print("mpl smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
