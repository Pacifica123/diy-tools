"""Безопасная subprocess-обёртка для GUI поверх devctl.

В обычном режиме разработки runner запускает текущий Python и GUI-скрипт
в специальном child-режиме. В собранном PyInstaller EXE он запускает этот же
EXE с флагом --devctl-child. Так GUI получает отдельный процесс, live-лог и
не требует установленного Python на машине пользователя.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass
class RunResult:
    command: list[str]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str
    json_data: dict | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class DevctlRunner:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).expanduser().resolve()

    def set_workspace(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()

    def _child_command(self, args: Iterable[str]) -> list[str]:
        args = list(args)
        if getattr(sys, "frozen", False):
            return [sys.executable, "--devctl-child", str(self.workspace), *args]
        gui_script = Path(__file__).resolve().with_name("devctl_gui.py")
        return [sys.executable, str(gui_script), "--devctl-child", str(self.workspace), *args]


    @staticmethod
    def _subprocess_env() -> dict[str, str]:
        env = os.environ.copy()
        # Важно для Windows: дочерний devctl печатает JSON с русским текстом.
        # GUI всегда читает UTF-8, поэтому заставляем child-процесс писать UTF-8.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    @staticmethod
    def _startupinfo() -> subprocess.STARTUPINFO | None:
        if os.name != "nt":
            return None
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return startupinfo

    @staticmethod
    def _creationflags() -> int:
        if os.name != "nt":
            return 0
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    @staticmethod
    def parse_last_json(text: str) -> dict | None:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{") or not line.endswith("}"):
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    def run(self, args: Iterable[str], timeout: int | None = 120) -> RunResult:
        command = self._child_command(args)
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                env=self._subprocess_env(),
                startupinfo=self._startupinfo(),
                creationflags=self._creationflags(),
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            return RunResult(
                command=command,
                cwd=self.workspace,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                json_data=self.parse_last_json(stdout + "\n" + stderr),
            )
        except Exception as exc:
            return RunResult(
                command=command,
                cwd=self.workspace,
                returncode=127,
                stdout="",
                stderr=f"Не удалось запустить devctl: {exc}",
                json_data=None,
            )

    def stream(
        self,
        args: Iterable[str],
        on_line: Callable[[str], None],
        on_done: Callable[[RunResult], None],
    ) -> subprocess.Popen | None:
        command = self._child_command(args)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=self._subprocess_env(),
                startupinfo=self._startupinfo(),
                creationflags=self._creationflags(),
            )
        except Exception as exc:
            on_done(
                RunResult(
                    command=command,
                    cwd=self.workspace,
                    returncode=127,
                    stdout="",
                    stderr=f"Не удалось запустить devctl: {exc}",
                    json_data=None,
                )
            )
            return None

        stdout_chunks: list[str] = []

        def pump() -> None:
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    stdout_chunks.append(line)
                    on_line(line)
                returncode = process.wait()
                stdout = "".join(stdout_chunks)
                on_done(
                    RunResult(
                        command=command,
                        cwd=self.workspace,
                        returncode=returncode,
                        stdout=stdout,
                        stderr="",
                        json_data=self.parse_last_json(stdout),
                    )
                )
            except Exception as exc:
                on_done(
                    RunResult(
                        command=command,
                        cwd=self.workspace,
                        returncode=1,
                        stdout="".join(stdout_chunks),
                        stderr=f"Ошибка чтения вывода devctl: {exc}",
                        json_data=None,
                    )
                )

        import threading

        threading.Thread(target=pump, daemon=True).start()
        return process
