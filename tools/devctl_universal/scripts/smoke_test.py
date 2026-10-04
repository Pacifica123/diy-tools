"""Smoke- и регрессионная проверка devctl_universal.

Собирает во временной папке настоящий workspace с Git-репозиторием и прогоняет через
`devctl.py` из капсулы основные сценарии: plan, успешный start, упавшую проверку с
автоматическим откатом, некорректный патч, reset. В капсулу ничего не пишется, push не
выполняется, сеть не нужна.
"""
from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
DEVCTL = ROOT / "devctl.py"
TOOL_ID = "devctl_universal"


def fail(message: str) -> None:
    raise SystemExit(f"{TOOL_ID} smoke FAILED: {message}")


def capsule_listing() -> list[str]:
    return sorted(path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*") if path.is_file())


def run_devctl(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    env.pop("DEVCTL_WORKSPACE", None)
    return subprocess.run(
        [sys.executable, "-B", str(DEVCTL), "-w", str(workspace), *args],
        cwd=workspace, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def git(project: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        fail(f"git {' '.join(args)}: {result.stderr}")
    return result.stdout


def make_patch(
    workspace: Path, name: str, patch_id: str, files: dict[str, str], *, delete: tuple[str, ...] = (), check: str | None = None,
) -> Path:
    manifest = {
        "formatVersion": 1,
        "patchId": patch_id,
        "title": f"Проверочный патч {patch_id}",
        "summary": "Патч создан smoke-тестом devctl_universal.",
        "apply": {"filesRoot": "files", "delete": [{"path": path} for path in delete]},
        "checks": [{"name": "check", "cwd": ".", "command": check, "timeoutSeconds": 60}] if check else [],
        "commit": {"message": f"test: {patch_id}"},
        "archive": {"nameSlug": patch_id},
    }
    path = workspace / "patches" / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for rel, text in files.items():
            archive.writestr(f"files/{rel}", text)
    return path


def last_json_line(text: str) -> dict:
    for line in reversed(text.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    fail(f"в выводе нет JSON-строки:\n{text}")
    raise AssertionError


def check_static() -> str:
    for required in ("gui/devctl_gui.py", "gui/devctl_runner.py", "docs/patch-manifest.example.json", "docs/CONTRACT.md", "CHANGELOG.md"):
        if not (ROOT / required).is_file():
            fail(f"нет файла {required}")
    example = json.loads((ROOT / "docs" / "patch-manifest.example.json").read_text(encoding="utf-8"))
    passport = configparser.ConfigParser()
    passport.read(ROOT / "tool.ini", encoding="utf-8")
    if example.get("formatVersion") != passport.getint("data", "contract_version"):
        fail("contract_version в tool.ini не совпадает с formatVersion примера манифеста")
    result = subprocess.run(
        [sys.executable, "-B", str(DEVCTL), "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"),
    )
    if result.returncode != 0 or "devctl" not in result.stdout.lower():
        fail(f"--version: {result.stdout}{result.stderr}")
    version = result.stdout.strip().split()[-1]
    if not passport.get("tool", "version").startswith(version):
        fail(f"версия ядра {version} не совпадает с началом версии в tool.ini")
    return result.stdout.strip()


def end_to_end(base: Path) -> None:
    workspace = base / "рабочая область с пробелом"
    workspace.mkdir()
    created = run_devctl(workspace, "init", "--workspace", str(workspace), "--project", "project", "--create-project", "--git-init", "--branch", "main")
    if created.returncode != 0:
        fail(f"init: {created.stdout}{created.stderr}")
    project = workspace / "project"
    for key, value in (("user.email", "smoke@example.invalid"), ("user.name", "smoke"), ("core.autocrlf", "false"), ("commit.gpgsign", "false")):
        git(project, "config", key, value)
    (project / "README.md").write_text("# Проект\n", encoding="utf-8")
    (project / "устаревший файл.txt").write_text("будет удалён патчем\n", encoding="utf-8")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "initial")
    base_head = git(project, "rev-parse", "HEAD").strip()

    # 1. plan ничего не меняет.
    good = make_patch(
        workspace, "patch_20260101_100000_good.zip", "smoke-good",
        {"README.md": "# Проект\n\nИзменено патчем.\n", "папка с пробелом/новый файл.txt": "привет\n"},
        delete=("устаревший файл.txt",),
        check=f'"{sys.executable}" -c "import pathlib,sys; sys.exit(0 if pathlib.Path(\'README.md\').is_file() else 1)"',
    )
    plan = run_devctl(workspace, "plan")
    if plan.returncode != 0 or git(project, "status", "--porcelain").strip() or git(project, "rev-parse", "HEAD").strip() != base_head:
        fail(f"plan изменил проект или завершился ошибкой:\n{plan.stdout}{plan.stderr}")
    if any((workspace / "archives").iterdir()):
        fail("plan создал архивы")

    # 2. Успешный start: коммит с трейлерами, снимки, копия UTS, запись в журнале.
    started = run_devctl(workspace, "start", "--no-push", "--json")
    if started.returncode != 0:
        fail(f"start: {started.stdout}{started.stderr}")
    payload = last_json_line(started.stdout)
    if payload.get("status") != "applied" or not payload.get("commitSha"):
        fail(f"start не сообщил applied/commitSha: {payload}")
    message = git(project, "log", "-1", "--format=%B")
    for trailer in ("Patch-Id: smoke-good", "Patch-SHA256: ", "Devctl-Version: "):
        if trailer not in message:
            fail(f"в коммите нет трейлера {trailer!r}:\n{message}")
    if (project / "устаревший файл.txt").exists() or not (project / "папка с пробелом" / "новый файл.txt").is_file():
        fail("патч применён не полностью")
    if git(project, "status", "--porcelain").strip():
        fail("после start рабочее дерево не чистое")
    run_dirs = [path for path in (workspace / "archives").iterdir() if path.is_dir()]
    if len(run_dirs) != 1:
        fail(f"ожидался один каталог запуска, найдено {len(run_dirs)}")
    names = sorted(path.name for path in run_dirs[0].iterdir())
    if not any(name.startswith("pre_") for name in names) or not any(name.startswith("post_") for name in names) or "report.md" not in names:
        fail(f"в каталоге запуска нет pre/post/report: {names}")
    uts = [path for path in (workspace / "UserTestSpace").iterdir() if path.is_dir()]
    if len(uts) != 1 or not (uts[0] / "project" / "README.md").is_file():
        fail("копия в UserTestSpace не создана")
    state = json.loads((workspace / ".devctl" / "state.json").read_text(encoding="utf-8"))
    if [run["status"] for run in state["runs"]] != ["applied"]:
        fail(f"журнал запусков: {state['runs']}")
    good_head = git(project, "rev-parse", "HEAD").strip()

    # 3. Повторный start: применять нечего, код 0, ничего не меняется.
    again = run_devctl(workspace, "start", "--no-push")
    if again.returncode != 0 or git(project, "rev-parse", "HEAD").strip() != good_head:
        fail(f"повторный start что-то изменил:\n{again.stdout}{again.stderr}")

    # 4. Флаг D: упавшая проверка -> failed-снимок, автоматический откат, плохой патч убран.
    bad = make_patch(
        workspace, "patch_20260102_100000_bad.zip", "smoke-bad",
        {"README.md": "# СЛОМАНО\n", "мусор.txt": "не должен остаться\n"},
        check=f'"{sys.executable}" -c "import sys; print(\'проверка намеренно падает\'); sys.exit(3)"',
    )
    failed = run_devctl(workspace, "start", "--no-push", "--json")
    if failed.returncode != 1:
        fail(f"упавшая проверка должна давать код 1, получен {failed.returncode}:\n{failed.stdout}{failed.stderr}")
    if git(project, "rev-parse", "HEAD").strip() != good_head or git(project, "status", "--porcelain").strip():
        fail("после упавшей проверки проект не возвращён в прежнее состояние")
    if (project / "мусор.txt").exists() or "СЛОМАНО" in (project / "README.md").read_text(encoding="utf-8"):
        fail("файлы упавшего патча остались в проекте")
    if bad.exists():
        fail("плохой патч не удалён из patches/")
    failed_dirs = [path for path in (workspace / "archives").iterdir() if path.is_dir() and path not in run_dirs]
    if len(failed_dirs) != 1 or not any(item.name.startswith("failed_") for item in failed_dirs[0].iterdir()):
        fail("нет failed-снимка упавшего запуска")
    report = (failed_dirs[0] / "report.md").read_text(encoding="utf-8")
    if "failed" not in report:
        fail("в отчёте упавшего запуска нет статуса failed")

    # 5. Небезопасный путь в патче: отказ, проект не тронут.
    evil = workspace / "patches" / "patch_20260103_100000_evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "formatVersion": 1, "patchId": "smoke-evil", "title": "t", "summary": "s",
            "apply": {"filesRoot": "files", "delete": []}, "checks": [], "commit": {"message": "x"},
        }))
        archive.writestr("files/../outside.txt", "выход за пределы проекта\n")
    rejected = run_devctl(workspace, "start", "--no-push")
    if rejected.returncode != 2:
        fail(f"патч с ../ должен давать код 2, получен {rejected.returncode}:\n{rejected.stdout}{rejected.stderr}")
    if (workspace / "outside.txt").exists() or git(project, "rev-parse", "HEAD").strip() != good_head or git(project, "status", "--porcelain").strip():
        fail("небезопасный патч изменил файлы")
    evil.unlink(missing_ok=True)

    # 6. reset убирает ручные правки и неотслеживаемые файлы.
    (project / "README.md").write_text("ручная правка\n", encoding="utf-8")
    (project / "черновик.tmp").write_text("x\n", encoding="utf-8")
    reset = run_devctl(workspace, "reset", "--keep-patch")
    if reset.returncode != 0 or git(project, "status", "--porcelain").strip():
        fail(f"reset не очистил проект:\n{reset.stdout}{reset.stderr}")

    # 7. status в JSON читается программой.
    status = run_devctl(workspace, "status", "--json")
    if status.returncode != 0 or not isinstance(last_json_line(status.stdout), dict):
        fail("status --json не вернул JSON")
    if good.exists() is False:
        fail("применённый патч не должен удаляться из patches/")


def main() -> int:
    before = capsule_listing()
    version_line = check_static()
    print(version_line)
    if shutil.which("git") is None:
        print("git не найден: проверены только --version, паспорт и документы; сквозной сценарий ПРОПУЩЕН")
    else:
        with tempfile.TemporaryDirectory(prefix=f"{TOOL_ID}_smoke_") as tmp:
            end_to_end(Path(tmp))
        print("GUI (Tkinter) автоматически не проверяется")
    after = capsule_listing()
    if before != after:
        fail(f"проверка изменила состав капсулы: {sorted(set(before) ^ set(after))}")
    print(f"{TOOL_ID} smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
