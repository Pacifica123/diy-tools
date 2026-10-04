"""Smoke- и регрессионный тест video_converter.

Запуск из любой папки:  python3 /путь/к/tools/video_converter/scripts/smoke_test.py

Тест пишет только во временную папку, не использует сеть и не требует настоящего ffmpeg:
- dry-run и JSON-отчёт сравниваются с examples/output_expected;
- реальный (не dry-run) путь, --overwrite, --delete-originals и ошибки проверяются
  на копии examples/input с заглушкой ffmpeg, созданной во временной папке;
- если в системе есть настоящий ffmpeg с libx264 и aac, дополнительно конвертируется
  крошечный синтетический ролик; если нет — этот шаг пропускается с сообщением.

Обновить эталоны после осознанного изменения контракта:
    python3 scripts/smoke_test.py --update-expected
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import configparser  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

TOOL_ID = "video_converter"
ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src" / "cli.py"
EXAMPLES_INPUT = ROOT / "examples" / "input"
EXPECTED_DIR = ROOT / "examples" / "output_expected"
UPDATE_EXPECTED = "--update-expected" in sys.argv[1:]
TIMEOUT = 120

MISSING_FFMPEG = "ffmpeg-которого-нет-video-converter-smoke"

STUB_SOURCE = r'''
import os
import sys

args = sys.argv[1:]
if "-version" in args:
    print("ffmpeg version stub")
    raise SystemExit(0)
source = args[args.index("-i") + 1]
output = args[-1]
name = os.path.basename(source)
tag = os.environ.get("VC_STUB_TAG", "")
fail = os.environ.get("VC_STUB_FAIL", "")
no_output = os.environ.get("VC_STUB_NO_OUTPUT", "")
if fail and fail in name:
    with open(output, "wb") as handle:
        handle.write(b"partial garbage")
    sys.stderr.buffer.write(b"stub: noise \xff\xfe is not utf-8\nstub: forced failure\n")
    raise SystemExit(1)
if no_output and no_output in name:
    raise SystemExit(0)
with open(source, "rb") as handle:
    data = handle.read()
with open(output, "wb") as handle:
    handle.write(b"STUB-MP4 " + tag.encode("utf-8") + b"\n" + data)
'''


class SmokeFailure(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def note(message: str) -> None:
    print(f"[{TOOL_ID}] {message}")


def stub_content(tag: str, source_bytes: bytes) -> bytes:
    return b"STUB-MP4 " + tag.encode("utf-8") + b"\n" + source_bytes


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("VC_STUB_TAG", "VC_STUB_FAIL", "VC_STUB_NO_OUTPUT"):
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if extra:
        env.update(extra)
    return env


def run_process(cmd: list[str], cwd: Path, extra_env: dict[str, str] | None = None) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=child_env(extra_env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise SmokeFailure(f"команда не завершилась за {TIMEOUT} с: {cmd}") from None
    stdout = completed.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    stderr = completed.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return completed.returncode, stdout, stderr


def run_cli(args: list[str], cwd: Path, extra_env: dict[str, str] | None = None) -> tuple[int, str, str]:
    return run_process([sys.executable, "-B", str(CLI), *args], cwd, extra_env)


def snapshot(directory: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in directory.rglob("*"):
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = path.read_bytes()
    return result


def listing(directory: Path) -> list[str]:
    return sorted(path.relative_to(directory).as_posix() for path in directory.rglob("*"))


def normalise_text(text: str, mapping: list[tuple[Path, str]]) -> str:
    """Заменяет нестабильные абсолютные пути метками и приводит разделители к '/'."""
    for path, label in sorted(mapping, key=lambda item: len(str(item[0])), reverse=True):
        text = text.replace(str(path), label)
    if os.sep != "/":
        text = text.replace(os.sep, "/")
    return text


def normalise_json(value, mapping: list[tuple[Path, str]]):
    if isinstance(value, str):
        return normalise_text(value, mapping)
    if isinstance(value, list):
        return [normalise_json(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: normalise_json(item, mapping) for key, item in value.items()}
    return value


def compare_expected(name: str, report: Path, stdout: str, mapping: list[tuple[Path, str]]) -> dict:
    """Сравнивает JSON-отчёт и stdout с examples/output_expected/<name>.*; возвращает исходный отчёт."""
    check(report.is_file(), f"{name}: отчёт не создан: {report}")
    raw = json.loads(report.read_text(encoding="utf-8"))
    actual_report = normalise_json(raw, mapping)
    actual_stdout = normalise_text(stdout, mapping)
    report_file = EXPECTED_DIR / f"{name}.report.json"
    stdout_file = EXPECTED_DIR / f"{name}.stdout.txt"
    if UPDATE_EXPECTED:
        EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps(actual_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        stdout_file.write_text(actual_stdout, encoding="utf-8", newline="\n")
        return raw
    check(report_file.is_file() and stdout_file.is_file(), f"{name}: нет эталона в {EXPECTED_DIR}")
    expected_report = json.loads(report_file.read_text(encoding="utf-8"))
    if actual_report != expected_report:
        raise SmokeFailure(
            f"{name}: JSON-отчёт не совпал с эталоном {report_file.name}\n"
            f"--- ожидалось ---\n{json.dumps(expected_report, ensure_ascii=False, indent=2, sort_keys=True)}\n"
            f"--- получено ---\n{json.dumps(actual_report, ensure_ascii=False, indent=2, sort_keys=True)}"
        )
    expected_stdout = stdout_file.read_text(encoding="utf-8").replace("\r\n", "\n")
    if actual_stdout != expected_stdout:
        raise SmokeFailure(
            f"{name}: stdout не совпал с эталоном {stdout_file.name}\n"
            f"--- ожидалось ---\n{expected_stdout}--- получено ---\n{actual_stdout}"
        )
    return raw


def copy_examples(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(EXAMPLES_INPUT, target)
    return target


def make_stub(base: Path) -> str | None:
    """Создаёт во временной папке исполняемую заглушку ffmpeg. None — если её нельзя запустить."""
    stub_dir = base / "заглушка ffmpeg"
    stub_dir.mkdir()
    script = stub_dir / "ffmpeg_stub.py"
    script.write_text(STUB_SOURCE, encoding="utf-8")
    if os.name == "nt":
        launcher = stub_dir / "ffmpeg_stub.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        def quote(text: str) -> str:
            return "'" + text.replace("'", "'\\''") + "'"

        launcher = stub_dir / "ffmpeg_stub"
        launcher.write_text(f"#!/bin/sh\nexec {quote(sys.executable)} {quote(str(script))} \"$@\"\n", encoding="utf-8")
        launcher.chmod(0o755)
    try:
        code, stdout, _ = run_process([str(launcher), "-version"], base)
    except OSError:
        return None
    if code != 0 or "stub" not in stdout:
        return None
    return str(launcher)


# --------------------------------------------------------------------------- проверки


def case_core_import() -> None:
    """Core импортируется без побочных эффектов; версия контракта согласована с tool.ini."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        import cli  # noqa: PLC0415
    finally:
        sys.path.pop(0)
    passport = configparser.ConfigParser(interpolation=None)
    passport.read(ROOT / "tool.ini", encoding="utf-8")
    check(
        str(cli.CONTRACT_VERSION) == passport.get("data", "contract_version", fallback=""),
        "CONTRACT_VERSION в src/cli.py не совпадает с [data] contract_version в tool.ini",
    )
    base = Path("входная папка")
    check(
        cli.output_path_for(base / "вложенная" / "клип 1.mkv", base, Path("выход")) == Path("выход") / "вложенная" / "клип 1.mp4",
        "output_path_for: структура вложенных папок не сохранена",
    )
    check(cli.output_path_for(base / "клип 1.mkv", base, None) == base / "клип 1.mp4", "output_path_for: mp4 должен быть рядом с mkv")


def case_dry_run(tmp: Path) -> None:
    """Флаг D: dry-run + отчёт. Регрессия прямо на examples/input (dry-run ничего не меняет)."""
    work = tmp / "dry run"
    work.mkdir()
    report = work / "отчёт dry-run.json"
    before = snapshot(EXAMPLES_INPUT)
    code, stdout, stderr = run_cli(
        [str(EXAMPLES_INPUT), "--dry-run", "--ffmpeg", MISSING_FFMPEG, "--report", str(report)], work
    )
    check(code == 0, f"dry_run: код возврата {code}, stderr: {stderr}")
    check(stderr == "", f"dry_run: неожиданный stderr: {stderr}")
    check(snapshot(EXAMPLES_INPUT) == before, "dry_run: dry-run изменил examples/input")
    data = compare_expected("dry_run", report, stdout, [(EXAMPLES_INPUT, "<INPUT>"), (report, "<REPORT>")])
    check(data.get("contract_version") == 1, "dry_run: в отчёте нет contract_version = 1")
    check(listing(work) == [report.name], f"dry_run: появились лишние файлы: {listing(work)}")

    # Опасные флаги вместе с --dry-run: на копии, ничего не должно измениться.
    copy = copy_examples(work / "копия примеров")
    out_dir = work / "выходная папка"
    report2 = work / "отчёт dry-run recursive.json"
    before = snapshot(copy)
    code, stdout, stderr = run_cli(
        [
            str(copy), "--dry-run", "--recursive", "--overwrite", "--delete-originals",
            "--output-dir", str(out_dir), "--ffmpeg", MISSING_FFMPEG, "--report", str(report2),
        ],
        work,
    )
    check(code == 0, f"dry_run_recursive: код возврата {code}, stderr: {stderr}")
    check(snapshot(copy) == before, "dry_run_recursive: dry-run с --delete-originals/--overwrite изменил файлы")
    check(not out_dir.exists(), "dry_run_recursive: dry-run создал выходную папку")
    compare_expected(
        "dry_run_recursive", report2, stdout, [(copy, "<INPUT>"), (out_dir, "<OUTPUT>"), (report2, "<REPORT>")]
    )


def case_stub_conversion(tmp: Path, stub: str) -> None:
    """Флаг D: реальный путь на копии — пропуск существующих, --overwrite, --delete-originals, ошибки."""
    work = tmp / "stub run"
    work.mkdir()
    copy = copy_examples(work / "копия примеров")
    original = snapshot(copy)
    mkv = original["clip one.mkv"]

    # 1. Обычный запуск: ничего не удаляется, существующий mp4 не перезаписывается.
    report = work / "отчёт convert.json"
    code, stdout, stderr = run_cli(
        [str(copy), "--recursive", "--ffmpeg", stub, "--report", str(report)], work, {"VC_STUB_TAG": "run1"}
    )
    check(code == 0, f"convert: код возврата {code}, stderr: {stderr}")
    compare_expected("convert", report, stdout, [(copy, "<INPUT>"), (report, "<REPORT>")])
    expected_tree = dict(original)
    expected_tree["clip one.mp4"] = stub_content("run1", mkv)
    expected_tree["тестовое видео.mp4"] = stub_content("run1", original["тестовое видео.mkv"])
    expected_tree["вложенная папка/nested clip.mp4"] = stub_content("run1", original["вложенная папка/nested clip.mkv"])
    after = snapshot(copy)
    check(after.get("already done.mp4") == original["already done.mp4"], "convert: существующий mp4 перезаписан без --overwrite")
    check(all(after.get(name) == data for name, data in original.items()), "convert: исходные файлы изменены или удалены")
    check(after == expected_tree, f"convert: неожиданное содержимое папки: {sorted(after)}")

    # 2. --overwrite --delete-originals с двумя сбоями: оригинал удаляется только после успеха,
    #    при сбое прежний mp4 остаётся целым и не остаётся временных файлов.
    report2 = work / "отчёт delete overwrite.json"
    code, stdout, stderr = run_cli(
        [str(copy), "--recursive", "--overwrite", "--delete-originals", "--ffmpeg", stub, "--report", str(report2)],
        work,
        {"VC_STUB_TAG": "run2", "VC_STUB_FAIL": "clip one", "VC_STUB_NO_OUTPUT": "nested clip"},
    )
    check(code == 1, f"delete_overwrite: ожидался код 1 (были ошибки), получен {code}; stderr: {stderr}")
    check("Traceback" not in stderr, f"delete_overwrite: traceback в stderr: {stderr}")
    compare_expected("delete_overwrite", report2, stdout, [(copy, "<INPUT>"), (report2, "<REPORT>")])
    expected_tree["already done.mp4"] = stub_content("run2", original["already done.mkv"])
    expected_tree["тестовое видео.mp4"] = stub_content("run2", original["тестовое видео.mkv"])
    del expected_tree["already done.mkv"]
    del expected_tree["тестовое видео.mkv"]
    after = snapshot(copy)
    check("clip one.mkv" in after, "delete_overwrite: оригинал удалён, хотя ffmpeg завершился с ошибкой")
    check("вложенная папка/nested clip.mkv" in after, "delete_overwrite: оригинал удалён, хотя выходной файл не создан")
    check(after.get("clip one.mp4") == stub_content("run1", mkv), "delete_overwrite: прежний mp4 испорчен неудачной перезаписью")
    check(not any(name.endswith(".vc-partial.mp4") for name in after), "delete_overwrite: остался временный файл .vc-partial.mp4")
    check(after == expected_tree, f"delete_overwrite: неожиданное содержимое папки: {sorted(after)}")

    # 3. --output-dir по относительному пути: структура папок сохраняется, исходники не тронуты.
    work3 = tmp / "output dir run"
    work3.mkdir()
    copy3 = copy_examples(work3 / "исходные видео")
    report3 = work3 / "отчёт output dir.json"
    code, stdout, stderr = run_cli(
        ["исходные видео", "--recursive", "--output-dir", "готовые файлы", "--ffmpeg", stub, "--report", "отчёт output dir.json"],
        work3,
        {"VC_STUB_TAG": "run3"},
    )
    check(code == 0, f"output_dir: код возврата {code}, stderr: {stderr}")
    out_dir = work3 / "готовые файлы"
    compare_expected("output_dir", report3, stdout, [(copy3, "<INPUT>"), (out_dir, "<OUTPUT>"), (report3, "<REPORT>")])
    check(snapshot(copy3) == original, "output_dir: исходная папка изменена")
    check(
        listing(out_dir) == ["already done.mp4", "clip one.mp4", "вложенная папка", "вложенная папка/nested clip.mp4", "тестовое видео.mp4"],
        f"output_dir: неожиданное содержимое выходной папки: {listing(out_dir)}",
    )

    # 4. --delete-originals без --report: предупреждение в stderr.
    code, stdout, stderr = run_cli(
        ["исходные видео", "--delete-originals", "--output-dir", "готовые файлы", "--ffmpeg", stub], work3, {"VC_STUB_TAG": "run4"}
    )
    check(code == 0, f"skip_delete: код возврата {code}, stderr: {stderr}")
    check("--delete-originals без --report" in stderr, "skip_delete: нет предупреждения об удалении без отчёта")
    check(snapshot(copy3) == original, "skip_delete: оригинал удалён, хотя файл был пропущен (выход уже существует)")
    check("Удалено оригиналов: 0" in stdout and "Пропущено: 3" in stdout, f"skip_delete: неожиданная сводка:\n{stdout}")


def case_errors(tmp: Path) -> None:
    """Понятные русские сообщения и коды возврата при ошибках запуска."""
    work = tmp / "errors"
    work.mkdir()
    copy = copy_examples(work / "копия примеров")
    before = snapshot(copy)
    report = work / "report.json"

    code, stdout, stderr = run_cli([str(copy), "--ffmpeg", MISSING_FFMPEG, "--report", str(report)], work)
    check(code == 2, f"missing_ffmpeg: ожидался код 2, получен {code}")
    check("ffmpeg не найден" in stderr, f"missing_ffmpeg: нет понятного сообщения: {stderr}")
    check(snapshot(copy) == before and not report.exists(), "missing_ffmpeg: без ffmpeg что-то было изменено")

    code, stdout, stderr = run_cli([str(work / "нет такой папки"), "--dry-run"], work)
    check(code == 2 and "папка не найдена" in stderr, f"missing_dir: код {code}, stderr: {stderr}")

    empty = work / "пустая папка"
    empty.mkdir()
    code, stdout, stderr = run_cli([str(empty), "--dry-run"], work)
    check(code == 0 and "Нет файлов .mkv" in stdout and "Найдено: 0" in stdout, f"empty_dir: код {code}, stdout: {stdout}")

    code, stdout, stderr = run_cli(["--help"], work)
    check(code == 0 and "--dry-run" in stdout and "--delete-originals" in stdout, "help: --help не описывает основные флаги")


def case_launcher(tmp: Path) -> None:
    """run.sh не меняет текущую папку: относительные пути считаются от папки запуска."""
    shell = shutil.which("sh")
    if os.name == "nt" or shell is None or shutil.which("python3") is None:
        note("run.sh не проверялся: нет sh/python3 в PATH или это Windows (run.bat автоматически не проверяется)")
        return
    work = tmp / "launcher run"
    work.mkdir()
    copy_examples(work / "мои видео")
    code, stdout, stderr = run_process(
        [shell, str(ROOT / "run.sh"), "мои видео", "--dry-run", "--report", "отчёт запуска.json"], work
    )
    check(code == 0, f"launcher: run.sh вернул {code}; stderr: {stderr}")
    report = work / "отчёт запуска.json"
    check(report.is_file(), "launcher: отчёт по относительному пути не появился в папке запуска (лаунчер сменил папку?)")
    data = json.loads(report.read_text(encoding="utf-8"))
    check(data["summary"]["found"] == 3 and data["summary"]["planned"] == 2, f"launcher: неожиданная сводка: {data['summary']}")


def case_real_ffmpeg(tmp: Path) -> None:
    """Настоящая конвертация крошечного синтетического ролика, если ffmpeg доступен."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        note("ffmpeg не найден: настоящая конвертация пропущена (dry-run и заглушка проверены)")
        return
    work = tmp / "real ffmpeg"
    source_dir = work / "синтетика с пробелом"
    source_dir.mkdir(parents=True)
    try:
        code, encoders, _ = run_process([ffmpeg, "-hide_banner", "-encoders"], work)
    except OSError as exc:
        note(f"ffmpeg не запускается ({exc}): настоящая конвертация пропущена")
        return
    words = encoders.split()
    if code != 0 or "libx264" not in words or "aac" not in words:
        note("в этой сборке ffmpeg нет кодировщиков libx264/aac: настоящая конвертация пропущена")
        return
    source = source_dir / "пробный ролик 1.mkv"
    code, _, stderr = run_process(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-shortest", str(source),
        ],
        work,
    )
    if code != 0 or not source.is_file() or source.stat().st_size == 0:
        last = stderr.strip().splitlines()[-1:] or [""]
        note(f"ffmpeg не смог создать синтетический .mkv ({last[0]}): настоящая конвертация пропущена")
        return
    source_bytes = source.read_bytes()
    out_dir = work / "результат"
    report = work / "report.json"
    code, stdout, stderr = run_cli([str(source_dir), "--output-dir", str(out_dir), "--report", str(report)], work)
    check(code == 0, f"real_ffmpeg: код возврата {code}\nstdout: {stdout}\nstderr: {stderr}")
    output = out_dir / "пробный ролик 1.mp4"
    check(output.is_file() and output.stat().st_size > 0, "real_ffmpeg: mp4 не создан или пуст")
    check(listing(out_dir) == [output.name], f"real_ffmpeg: лишние файлы в выходной папке: {listing(out_dir)}")
    check(source.read_bytes() == source_bytes, "real_ffmpeg: оригинал изменён или удалён")
    data = json.loads(report.read_text(encoding="utf-8"))
    check(data["summary"]["created"] == 1 and data["summary"]["errors"] == 0, f"real_ffmpeg: сводка {data['summary']}")
    check(data["results"][0]["status"] == "created", f"real_ffmpeg: статус {data['results'][0]}")

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        note("ffprobe не найден: кодеки результата не проверялись")
    else:
        code, probe, stderr = run_process(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_name", "-of", "json", str(output)], work
        )
        check(code == 0, f"real_ffmpeg: ffprobe не прочитал результат: {stderr}")
        codecs = sorted(stream.get("codec_name", "") for stream in json.loads(probe).get("streams", []))
        check(codecs == ["aac", "h264"], f"real_ffmpeg: ожидались кодеки aac + h264, получены {codecs}")

    # Повторный запуск без --overwrite, но с --delete-originals: результат пропущен, оригинал цел.
    mp4_bytes = output.read_bytes()
    code, stdout, stderr = run_cli([str(source_dir), "--output-dir", str(out_dir), "--delete-originals", "--report", str(report)], work)
    check(code == 0, f"real_ffmpeg (повтор): код возврата {code}; stderr: {stderr}")
    data = json.loads(report.read_text(encoding="utf-8"))
    check(data["results"][0]["status"] == "skipped", f"real_ffmpeg (повтор): ожидался skipped, получено {data['results'][0]}")
    check(output.read_bytes() == mp4_bytes and source.read_bytes() == source_bytes, "real_ffmpeg (повтор): файлы изменены")
    note("настоящая конвертация через ffmpeg проверена")


def run() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    capsule_before = listing(ROOT)
    try:
        try:
            os.fsencode("кириллица")
        except UnicodeEncodeError:
            raise SmokeFailure(
                f"кодировка файловой системы ({sys.getfilesystemencoding()}) не передаёт кириллицу в именах файлов; "
                "запустите тест в UTF-8 локали или с PYTHONUTF8=1"
            ) from None
        check(CLI.is_file(), f"не найден {CLI}")
        check(EXAMPLES_INPUT.is_dir(), f"не найдена папка примеров {EXAMPLES_INPUT}")
        case_core_import()
        with tempfile.TemporaryDirectory(prefix="video_converter_smoke_") as tmp_name:
            tmp = Path(tmp_name).resolve()
            case_dry_run(tmp)
            case_errors(tmp)
            stub = make_stub(tmp)
            if stub is None:
                check(not UPDATE_EXPECTED, "заглушку ffmpeg не удалось запустить: эталоны обновить нельзя")
                note(
                    "заглушку ffmpeg не удалось запустить (временная папка без права запуска?): "
                    "проверки --overwrite/--delete-originals на заглушке ПРОПУЩЕНЫ"
                )
            else:
                case_stub_conversion(tmp, stub)
            case_launcher(tmp)
            case_real_ffmpeg(tmp)
        if not UPDATE_EXPECTED:
            check(listing(ROOT) == capsule_before, "после теста в капсуле изменился состав файлов (мусор или удаление)")
    except SmokeFailure as exc:
        print(f"{TOOL_ID} smoke FAILED: {exc}", file=sys.stderr)
        return 1
    if UPDATE_EXPECTED:
        print(f"{TOOL_ID}: эталоны в examples/output_expected обновлены; проверьте diff и запустите тест ещё раз")
        return 0
    print(f"{TOOL_ID} smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
