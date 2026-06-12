from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from devctl_runner import DevctlRunner, RunResult
except ImportError:  # запуск как python -m gui.devctl_gui
    from .devctl_runner import DevctlRunner, RunResult  # type: ignore

APP_NAME = "devctl GUI"
APP_VERSION = "0.2.7"
BUNDLED_DEVCTL_VERSION = "0.6.7"


PATCH_PROMPT_TEMPLATE = """Ты работаешь с devctl workspace и должен вернуть не полный архив проекта, а полноценный devctl-патч.

Контекст devctl:
- workspace содержит project/, patches/, archives/, UserTestSpace/ и .devctl/;
- devctl применяет patch.zip из patches/ к папке project/;
- патч должен быть безопасным, воспроизводимым и понятным человеку;
- GUI/CLI ожидают структуру patch.zip с manifest.json, PATCH_SUMMARY.md и files/.
- devctl умеет reset, init --upgrade, автооткат failed start, UTS и автоочистку Python bytecode/cache.

Твоя задача:
1. Изучи текущие файлы проекта, которые нужно менять. Не придумывай содержимое вслепую.
2. Реализуй изменение минимально и аккуратно.
3. Собери devctl patch.zip, а не весь проект.
4. Проверь патч хотя бы синтаксически и, если возможно, через devctl plan/start на временном workspace.
5. В ответе дай ссылку на patch.zip, SHA-256, краткое описание и список проверок.

Обязательная структура архива:

```text
patch_YYYYMMDD_HHMMSS_short_slug.zip
  manifest.json
  PATCH_SUMMARY.md
  files/
    relative/path/in/project.ext
```

Правила для files/:
- пути внутри files/ должны быть относительными к project/;
- не клади абсолютные пути;
- не клади .git/, .env, секреты, __pycache__/, *.pyc, *.pyo, .pytest_cache/, .venv/, dist/, build/, node_modules/;
- если devctl копирует целые файлы, клади в files/ уже финальные версии изменённых файлов;
- не меняй unrelated-файлы ради косметики.

Минимальный manifest.json:

```json
{
  "formatVersion": 1,
  "patchId": "YYYY-MM-DD-short-slug",
  "title": "Короткое название патча",
  "summary": "Что делает патч и зачем.",
  "kind": "feature-or-fix",
  "createdAt": "YYYY-MM-DDTHH:MM:SSZ",
  "base": {
    "branch": "main",
    "expectedHead": null
  },
  "apply": {
    "filesRoot": "files",
    "delete": []
  },
  "checks": [
    {
      "name": "Python syntax без генерации __pycache__",
      "cwd": ".",
      "command": "python -c \"import ast,pathlib; files=['devctl.py']; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8'), filename=p) for p in files]\"",
      "requiredCommands": ["python"],
      "timeoutSeconds": 120
    }
  ],
  "commit": {
    "message": "feat: кратко описать изменение"
  },
  "push": {
    "remote": "origin",
    "branch": "main"
  },
  "archive": {
    "nameSlug": "short-slug",
    "exclude": [
      ".git/",
      ".venv/",
      "node_modules/",
      "target/",
      "dist/",
      "build/",
      "coverage/",
      "__pycache__/",
      ".pytest_cache/",
      ".env",
      ".env.*",
      "*.sqlite",
      "*.db"
    ]
  }
}
```

Для Python-проектов предпочитай проверку через ast.parse, а не py_compile, чтобы проверка не создавала __pycache__.

PATCH_SUMMARY.md должен объяснять:
- что меняется;
- зачем это нужно;
- основные файлы;
- риски;
- проверки;
- особые инструкции применения, если они есть.

Финальный ответ пользователю должен быть коротким:
- ссылка на patch.zip;
- SHA-256;
- что меняется;
- какие проверки прогнаны;
- если что-то не удалось проверить — честно указать.
"""

def configure_standard_streams() -> None:
    """Принудительно держим UTF-8 для child-процессов на Windows.

    Без этого Windows PowerShell/GUI-процессы могут отдать русскоязычный JSON
    в cp1251, а родительский GUI прочитает его как UTF-8 и покажет «����».
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def bundled_root() -> Path:
    """Где лежат devctl.py и bundled-ресурсы.

    В PyInstaller one-file это временный каталог _MEIPASS. Его нельзя
    использовать как рабочую область пользователя.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    return Path(__file__).resolve().parents[1]


def app_dir() -> Path:
    """Каталог exe/скрипта, видимый пользователю."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def default_workspace_path() -> Path:
    """Безопасная стартовая рабочая область для GUI.

    Раньше frozen-сборка стартовала из _MEIPASS, поэтому пользователь видел
    C:/Users/.../Temp/_MEI... и devctl закономерно падал. Если exe лежит в
    project/release, по умолчанию берём project. Иначе берём папку рядом с exe.
    """
    base = app_dir()
    if base.name.lower() == "release":
        return base.parent
    return base


def repo_root() -> Path:
    # Обратная совместимость для старых мест вызова: это именно root ресурсов.
    return bundled_root()


def run_devctl_child(argv: list[str]) -> int:
    if len(argv) < 2:
        print("[ОШИБКА] child-режим ожидает: --devctl-child <workspace> <devctl args...>", file=sys.stderr)
        return 2
    workspace = Path(argv[0]).expanduser().resolve()
    # Ядро devctl 0.5+ умеет явный workspace override через DEVCTL_WORKSPACE.
    # Оставляем chdir для обратной совместимости, но дополнительно фиксируем
    # workspace в окружении, чтобы status/plan/start не зависели от cwd child-процесса.
    os.environ["DEVCTL_WORKSPACE"] = str(workspace)
    devctl_args = argv[1:]
    if devctl_args and devctl_args[0] == "init":
        workspace.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)
    configure_standard_streams()
    root = bundled_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        import devctl
    except Exception as exc:
        print(f"[ОШИБКА] Не удалось импортировать devctl.py: {exc}", file=sys.stderr)
        return 2
    return int(devctl.main(devctl_args))


def app_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "devctl-gui" / "config.json"
    return Path.home() / ".config" / "devctl-gui" / "config.json"


def looks_like_pyinstaller_temp(path: Path) -> bool:
    return any(part.upper().startswith("_MEI") for part in path.parts)


def initial_workspace(config_data: dict) -> str:
    configured = config_data.get("lastWorkspace")
    if configured:
        try:
            candidate = Path(str(configured)).expanduser().resolve()
            # Старые сборки могли сохранить C:/Users/.../Temp/_MEI... в config.json.
            # Такой путь является временной распаковкой exe и не должен становиться
            # рабочей областью.
            if candidate.exists() and not looks_like_pyinstaller_temp(candidate):
                return str(candidate)
        except Exception:
            pass
    return str(default_workspace_path())


def load_config() -> dict:
    path = app_config_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data: dict) -> None:
    path = app_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def open_path(path: str | Path | None) -> None:
    if not path:
        messagebox.showinfo(APP_NAME, "Путь пока неизвестен.")
        return
    target = Path(path)
    try:
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except Exception as exc:
        messagebox.showerror(APP_NAME, f"Не удалось открыть путь:\n{target}\n\n{exc}")


class StatusCard(ttk.Frame):
    def __init__(self, master: tk.Misc, title: str):
        super().__init__(master, padding=10, style="Card.TFrame")
        self.title_label = ttk.Label(self, text=title, style="CardTitle.TLabel")
        self.title_label.pack(anchor="w")
        self.value_label = ttk.Label(self, text="—", style="CardMuted.TLabel", wraplength=230)
        self.value_label.pack(anchor="w", pady=(6, 0))

    def set(self, text: str, kind: str = "neutral") -> None:
        style = {
            "ok": "CardOk.TLabel",
            "warn": "CardWarn.TLabel",
            "bad": "CardBad.TLabel",
            "neutral": "CardMuted.TLabel",
        }.get(kind, "CardMuted.TLabel")
        self.value_label.configure(text=text, style=style)


class ToolTip:
    """Лёгкая tooltip-подсказка для компактных icon-кнопок.

    В нижней панели теперь показываются только монохромные символы, поэтому
    полный текст действия должен быть доступен без догадок. Делаем это без
    внешних зависимостей и без сложной графики, чтобы GUI оставался простым
    Tkinter-приложением.
    """

    def __init__(self, widget: tk.Widget, text: str, *, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self) -> None:
        if self._window is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 8
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        except tk.TclError:
            return
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            window,
            text=self.text,
            justify="left",
            background="#161b22",
            foreground="#f0f6fc",
            activebackground="#161b22",
            activeforeground="#f0f6fc",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=5,
            font=("Segoe UI", 9),
        )
        label.pack()
        self._window = window

    def _hide(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None


class InitWorkspaceDialog(tk.Toplevel):
    """Небольшой modal-dialog для создания нового devctl workspace."""

    def __init__(self, master: tk.Misc, *, initial_parent: Path, initial_name: str = "devctl-workspace") -> None:
        super().__init__(master)
        self.title("Инициализация workspace")
        self.resizable(False, False)
        self.result: dict[str, str] | None = None

        self.parent_var = tk.StringVar(value=str(initial_parent))
        self.name_var = tk.StringVar(value=initial_name)
        self.remote_var = tk.StringVar(value="")
        self.branch_var = tk.StringVar(value="main")

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Новый workspace", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(
            body,
            text="GUI создаст папку workspace и структуру devctl. Если указан GitHub/Git URL, project/ будет клонирован или синхронизирован через fetch/pull.",
            wraplength=560,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))

        ttk.Label(body, text="Куда поместить workspace:").grid(row=2, column=0, sticky="w")
        parent_entry = ttk.Entry(body, textvariable=self.parent_var, width=62)
        parent_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 10))
        ttk.Button(body, text="Выбрать...", command=self.choose_parent).grid(row=3, column=2, sticky="ew", padx=(8, 0), pady=(4, 10))

        ttk.Label(body, text="Название workspace:").grid(row=4, column=0, sticky="w")
        ttk.Entry(body, textvariable=self.name_var, width=62).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4, 10))

        ttk.Label(body, text="GitHub/Git remote URL для origin, необязательно:").grid(row=6, column=0, sticky="w")
        ttk.Entry(body, textvariable=self.remote_var, width=62).grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 10))

        ttk.Label(
            body,
            text="Если URL задан, GUI загрузит существующий remote-проект в project/ и явно выполнит fetch/pull выбранной ветки.",
            wraplength=560,
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(body, text="Основная ветка:").grid(row=9, column=0, sticky="w")
        ttk.Entry(body, textvariable=self.branch_var, width=20).grid(row=10, column=0, sticky="w", pady=(4, 16))

        buttons = ttk.Frame(body)
        buttons.grid(row=11, column=0, columnspan=3, sticky="e")
        ttk.Button(buttons, text="Отмена", command=self.cancel).pack(side="right")
        ttk.Button(buttons, text="Создать и открыть", command=self.accept).pack(side="right", padx=(0, 8))

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Return>", lambda _event: self.accept())
        self.bind("<Escape>", lambda _event: self.cancel())
        self.after(50, parent_entry.focus_set)

    def choose_parent(self) -> None:
        selected = filedialog.askdirectory(title="Выберите папку, внутри которой создать workspace", parent=self)
        if selected:
            self.parent_var.set(selected)

    @staticmethod
    def _validate_folder_name(name: str) -> str | None:
        value = name.strip()
        if not value:
            return "Название workspace не должно быть пустым."
        if value in {".", ".."}:
            return "Название workspace не должно быть '.' или '..'."
        if any(char in value for char in '<>:"/\\|?*'):
            return "Название workspace не должно содержать символы: < > : \" / \\ | ? *"
        return None

    def accept(self) -> None:
        parent = self.parent_var.get().strip()
        name = self.name_var.get().strip()
        branch = self.branch_var.get().strip() or "main"
        error = self._validate_folder_name(name)
        if error:
            messagebox.showerror(APP_NAME, error, parent=self)
            return
        if not parent:
            messagebox.showerror(APP_NAME, "Выберите родительскую директорию для workspace.", parent=self)
            return
        self.result = {
            "parent": parent,
            "name": name,
            "remoteUrl": self.remote_var.get().strip(),
            "branch": branch,
        }
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()


class DevctlGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1120x760")
        self.minsize(980, 640)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.current_process = None
        self.last_status: dict | None = None
        self.last_plan: dict | None = None
        self.last_report_path: str | None = None
        self.last_archive_path: str | None = None
        self.last_uts_path: str | None = None
        self.recommended_action_code = "refresh_status"

        self.config_data = load_config()
        default_workspace = initial_workspace(self.config_data)
        self.workspace_var = tk.StringVar(value=default_workspace)
        self.runner = DevctlRunner(default_workspace)

        self._setup_styles()
        self._build_ui()
        self.after(100, self.refresh_status)
        self.after(100, self._drain_events)

    def report_callback_exception(self, exc, val, tb) -> None:
        """Показываем ошибки GUI-callback прямо пользователю.

        В собранном .exe исключения Tkinter иначе легко выглядят как
        «кнопка не нажимается»: traceback уходит в невидимую консоль.
        """
        details = "".join(traceback.format_exception(exc, val, tb))
        self.set_text(self.report_text, "== ошибка GUI ==\n\n" + details)
        self.notebook.select(2)
        messagebox.showerror(APP_NAME, f"Ошибка в обработчике GUI:\n{val}", parent=self)

    def _setup_styles(self) -> None:
        self.configure(background="#0d1117")
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.colors = {
            "bg": "#0d1117",
            "panel": "#161b22",
            "panel2": "#010409",
            "border": "#30363d",
            "text": "#c9d1d9",
            "muted": "#8b949e",
            "ok": "#3fb950",
            "warn": "#d29922",
            "bad": "#f85149",
            "button": "#21262d",
            "button_active": "#30363d",
            "entry": "#0d1117",
            "select": "#264f78",
        }
        c = self.colors

        style.configure(".", background=c["bg"], foreground=c["text"], fieldbackground=c["entry"], bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"])
        style.configure("Main.TFrame", background=c["bg"])
        style.configure("Card.TFrame", background=c["panel"], relief="solid", borderwidth=1, bordercolor=c["border"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabel", font=("Segoe UI", 10), background=c["bg"], foreground=c["text"])
        style.configure("Header.TLabel", font=("Segoe UI", 15, "bold"), background=c["bg"], foreground="#f0f6fc")
        style.configure("Subtle.TLabel", font=("Segoe UI", 9), foreground=c["muted"], background=c["bg"])
        style.configure("CardTitle.TLabel", background=c["panel"], foreground="#f0f6fc", font=("Segoe UI", 10, "bold"))
        style.configure("CardMuted.TLabel", background=c["panel"], foreground=c["muted"], font=("Segoe UI", 10))
        style.configure("CardOk.TLabel", background=c["panel"], foreground=c["ok"], font=("Segoe UI", 10, "bold"))
        style.configure("CardWarn.TLabel", background=c["panel"], foreground=c["warn"], font=("Segoe UI", 10, "bold"))
        style.configure("CardBad.TLabel", background=c["panel"], foreground=c["bad"], font=("Segoe UI", 10, "bold"))
        style.configure("NextActionTitle.TLabel", background=c["panel"], foreground="#f0f6fc", font=("Segoe UI", 12, "bold"))
        style.configure("NextActionBody.TLabel", background=c["panel"], foreground=c["text"], font=("Segoe UI", 10))
        style.configure("NextActionOk.TLabel", background=c["panel"], foreground=c["ok"], font=("Segoe UI", 12, "bold"))
        style.configure("NextActionWarn.TLabel", background=c["panel"], foreground=c["warn"], font=("Segoe UI", 12, "bold"))
        style.configure("NextActionBad.TLabel", background=c["panel"], foreground=c["bad"], font=("Segoe UI", 12, "bold"))
        style.configure("Magic.TButton", font=("Segoe UI", 13, "bold"), padding=(18, 12), background="#238636", foreground="#ffffff", bordercolor="#2ea043")
        style.map("Magic.TButton", background=[("active", "#2ea043"), ("disabled", c["button"])], foreground=[("disabled", c["muted"])])
        style.configure("Action.TButton", font=("Segoe UI", 10), padding=(10, 7), background=c["button"], foreground=c["text"], bordercolor=c["border"])
        style.map("Action.TButton", background=[("active", c["button_active"]), ("disabled", c["button"])], foreground=[("disabled", "#6e7681")])
        style.configure("Icon.TButton", font=("Segoe UI Symbol", 12, "bold"), padding=(6, 5), background=c["button"], foreground=c["text"], bordercolor=c["border"])
        style.map("Icon.TButton", background=[("active", c["button_active"]), ("disabled", c["button"])], foreground=[("disabled", "#6e7681")])
        style.configure("TEntry", fieldbackground=c["entry"], foreground=c["text"], insertcolor=c["text"], bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"])
        style.configure("TNotebook", background=c["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=c["button"], foreground=c["muted"], padding=(12, 7))
        style.map("TNotebook.Tab", background=[("selected", c["panel"])], foreground=[("selected", "#f0f6fc")])
        style.configure("Vertical.TScrollbar", background=c["button"], troughcolor=c["panel2"], bordercolor=c["border"], arrowcolor=c["muted"])


    def _make_icon_button(self, master: tk.Misc, icon: str, tooltip: str, command) -> ttk.Button:
        """Создать компактную нижнюю кнопку: символ вместо длинного текста."""
        button = ttk.Button(master, text=icon, width=3, command=command, style="Icon.TButton")
        ToolTip(button, tooltip)
        return button

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14, style="Main.TFrame")
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root, style="Main.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Рабочая область", style="Header.TLabel").pack(side="left")
        ttk.Label(top, text=f"devctl v{BUNDLED_DEVCTL_VERSION} · GUI v{APP_VERSION}", style="Subtle.TLabel").pack(side="right")

        path_row = ttk.Frame(root, style="Main.TFrame")
        path_row.pack(fill="x", pady=(8, 12))
        self.path_entry = ttk.Entry(path_row, textvariable=self.workspace_var)
        self.path_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="Выбрать", command=self.choose_workspace, style="Action.TButton").pack(side="left", padx=(8, 0))
        self.init_top_btn = ttk.Button(path_row, text="Новый workspace", command=self.init_workspace, style="Action.TButton")
        self.init_top_btn.pack(side="left", padx=(8, 0))
        ttk.Button(path_row, text="Обновить", command=self.refresh_status, style="Action.TButton").pack(side="left", padx=(8, 0))

        cards = ttk.Frame(root, style="Main.TFrame")
        cards.pack(fill="x", pady=(0, 12))
        self.cards = {
            "project": StatusCard(cards, "Проект"),
            "git": StatusCard(cards, "Git"),
            "patch": StatusCard(cards, "Патч"),
            "uts": StatusCard(cards, "UTS"),
            "push": StatusCard(cards, "Push"),
        }
        for index, card in enumerate(self.cards.values()):
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            cards.columnconfigure(index, weight=1)

        self.next_action_frame = ttk.Frame(root, padding=12, style="Card.TFrame")
        self.next_action_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(self.next_action_frame, text="Следующее действие", style="CardTitle.TLabel").pack(anchor="w")
        self.next_action_title = ttk.Label(self.next_action_frame, text="Проверить workspace", style="NextActionTitle.TLabel", wraplength=980)
        self.next_action_title.pack(anchor="w", pady=(6, 0))
        self.next_action_body = ttk.Label(
            self.next_action_frame,
            text="GUI сейчас обновит статус и подскажет безопасный следующий шаг.",
            style="NextActionBody.TLabel",
            wraplength=980,
        )
        self.next_action_body.pack(anchor="w", pady=(4, 0))

        self.main_button = ttk.Button(root, text="Проверить workspace", command=self.perform_recommended_action, style="Magic.TButton")
        self.main_button.pack(fill="x", pady=(0, 10))

        # Панель действий должна быть видна сразу после запуска окна. Раньше она
        # находилась под растягиваемым notebook-логом и могла уезжать ниже
        # нижнего края окна, пока пользователь вручную не увеличит высоту.
        actions = ttk.Frame(root, style="Main.TFrame")
        actions.pack(fill="x", pady=(0, 8))
        self.init_btn = self._make_icon_button(actions, "＋", "Инициализировать workspace", self.init_workspace)
        self.status_btn = self._make_icon_button(actions, "●", "Показать статус", self.refresh_status)
        self.sync_btn = self._make_icon_button(actions, "⇄", "Синхронизировать workspace с GitHub: project -> archives -> UTS", self.sync_workspace)
        self.plan_btn = self._make_icon_button(actions, "☷", "Построить dry-run план", self.build_plan)
        self.start_btn = self._make_icon_button(actions, "▶", "Запустить конвейер с push по плану", lambda: self.start_pipeline(False))
        self.no_push_btn = self._make_icon_button(actions, "⊘", "Запустить конвейер без push", lambda: self.start_pipeline(True))
        self.upgrade_btn = self._make_icon_button(actions, "⇧", "Безопасно обновить структуру workspace", self.upgrade_workspace)
        self.reset_btn = self._make_icon_button(actions, "↺", "Reset project: git reset --hard + git clean", self.reset_project)
        self.report_btn = self._make_icon_button(actions, "☰", "Открыть последний отчёт", self.open_report)
        self.archives_btn = self._make_icon_button(actions, "▤", "Открыть archives/", self.open_archives)
        self.uts_btn = self._make_icon_button(actions, "◇", "Открыть UserTestSpace/ или свежую UTS-копию", self.open_uts)
        self.project_btn = self._make_icon_button(actions, "⌂", "Открыть project/", self.open_project)
        self.copy_output_btn = self._make_icon_button(actions, "⧉", "Скопировать текущий вывод активной вкладки", self.copy_current_output)
        self.copy_prompt_btn = self._make_icon_button(actions, "✎", "Скопировать prompt-патча", self.copy_patch_prompt)
        self.action_buttons = (
            self.init_btn,
            self.status_btn,
            self.sync_btn,
            self.plan_btn,
            self.start_btn,
            self.no_push_btn,
            self.upgrade_btn,
            self.reset_btn,
            self.report_btn,
            self.archives_btn,
            self.uts_btn,
            self.project_btn,
            self.copy_output_btn,
            self.copy_prompt_btn,
        )
        for index, widget in enumerate(self.action_buttons):
            widget.grid(row=0, column=index, sticky="w", padx=(0, 6))
        actions.columnconfigure(len(self.action_buttons), weight=1)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)
        self.plan_text = self._make_text_tab("План")
        self.run_text = self._make_text_tab("Запуск")
        self.report_text = self._make_text_tab("Отчёт")

    def _make_text_tab(self, title: str) -> tk.Text:
        frame = ttk.Frame(self.notebook, style="Main.TFrame")
        self.notebook.add(frame, text=title)
        colors = getattr(self, "colors", {})
        text = tk.Text(
            frame,
            wrap="word",
            font=("Consolas", 10),
            undo=False,
            background=colors.get("panel2", "#010409"),
            foreground=colors.get("text", "#c9d1d9"),
            insertbackground=colors.get("text", "#c9d1d9"),
            selectbackground=colors.get("select", "#264f78"),
            relief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=colors.get("border", "#30363d"),
            highlightcolor=colors.get("border", "#30363d"),
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview, style="Vertical.TScrollbar")
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return text

    def set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", value)
        widget.configure(state="disabled")

    def append_run(self, value: str) -> None:
        self.run_text.configure(state="normal")
        self.run_text.insert("end", value)
        self.run_text.see("end")
        self.run_text.configure(state="disabled")

    def _set_next_action(self, code: str, title: str, details: str, button_text: str, kind: str = "neutral") -> None:
        self.recommended_action_code = code
        title_style = {
            "ok": "NextActionOk.TLabel",
            "warn": "NextActionWarn.TLabel",
            "bad": "NextActionBad.TLabel",
            "neutral": "NextActionTitle.TLabel",
        }.get(kind, "NextActionTitle.TLabel")
        self.next_action_title.configure(text=title, style=title_style)
        self.next_action_body.configure(text=details)
        self.main_button.configure(text=button_text)

    def perform_recommended_action(self) -> None:
        actions = {
            "init_workspace": self.init_workspace,
            "choose_workspace": self.choose_workspace,
            "refresh_status": self.refresh_status,
            "sync_workspace": self.sync_workspace,
            "open_patches": self.open_patches,
            "open_project": self.open_project,
            "show_git_status": self.show_git_status,
            "reset_project": self.reset_project,
            "upgrade_workspace": self.upgrade_workspace,
            "build_plan": self.build_plan,
            "start_pipeline": lambda: self.start_pipeline(False),
            "open_report": self.open_report,
            "open_uts": self.open_uts,
            "copy_patch_prompt": self.copy_patch_prompt,
        }
        action = actions.get(self.recommended_action_code, self.refresh_status)
        action()

    @staticmethod
    def _workspace_upgrade_details(workspace_config: dict) -> str:
        missing = []
        missing.extend(workspace_config.get("missingFields") or [])
        missing.extend(workspace_config.get("missingArchiveExcludes") or [])
        missing.extend(workspace_config.get("missingDirs") or [])
        return ", ".join(str(item) for item in missing[:8]) or "структура workspace устарела"

    def _recommend_from_status(self, data: dict) -> None:
        workspace = data.get("workspace", {}) if isinstance(data.get("workspace"), dict) else {}
        git = data.get("git", {}) if isinstance(data.get("git"), dict) else {}
        patches = data.get("patches", {}) if isinstance(data.get("patches"), dict) else {}
        latest = patches.get("latest")

        project_root = workspace.get("projectRoot") or "project/"
        patches_dir = workspace.get("patchesDir") or "patches/"
        workspace_config = data.get("workspaceConfig", {}) if isinstance(data.get("workspaceConfig"), dict) else {}
        upgrade_available = bool(workspace.get("projectExists") and workspace_config.get("upgradeAvailable"))
        upgrade_details = self._workspace_upgrade_details(workspace_config)

        if not workspace.get("projectExists"):
            self._set_next_action(
                "init_workspace",
                "Создать или выбрать рабочую область devctl",
                f"В текущем workspace не найден project/: {project_root}. Можно создать новый workspace мастером или выбрать уже существующий.",
                "Инициализировать workspace",
                "warn",
            )
            return

        if not git.get("available"):
            self._set_next_action(
                "refresh_status",
                "Установить или добавить Git в PATH",
                "devctl не видит git.exe/git. Установите Git for Windows или добавьте его в PATH, затем обновите статус.",
                "Обновить статус",
                "bad",
            )
            return

        if not git.get("isRepository"):
            self._set_next_action(
                "open_project",
                "Проверить Git-репозиторий в project/",
                f"Папка project/ найдена, но не является Git-репозиторием: {project_root}. Откройте её и выполните git init или создайте workspace через мастер.",
                "Открыть project/",
                "bad",
            )
            return

        if git.get("clean") is False:
            self._set_next_action(
                "reset_project",
                "Рабочее дерево project/ загрязнено",
                "Можно открыть git status для ручной проверки или нажать reset: GUI вызовет devctl reset после отдельного предупреждения и откатит project/ через git reset --hard + git clean -fd.",
                "Reset project",
                "warn",
            )
            return

        if not latest:
            if self.last_report_path:
                self._set_next_action(
                    "open_report",
                    "Посмотреть отчёт последнего запуска",
                    "Неприменённых патчей сейчас нет. Можно открыть последний отчёт или добавить новый patch.zip в папку patches/.",
                    "Открыть последний отчёт",
                    "ok",
                )
            elif upgrade_available:
                self._set_next_action(
                    "upgrade_workspace",
                    "Безопасно обновить структуру workspace",
                    f"devctl видит, что workspace можно актуализировать: {upgrade_details}. Команда init --upgrade не трогает project/ и пользовательские пути, а только добавляет недостающую инфраструктуру.",
                    "Обновить структуру workspace",
                    "warn",
                )
            else:
                self._set_next_action(
                    "sync_workspace",
                    "Синхронизировать workspace с GitHub",
                    "Неприменённых патчей нет. Можно одной кнопкой привести project/ к актуальному origin/ветке, затем создать свежий архив в archives/ и развернуть копию в UserTestSpace/. Для нового патча по-прежнему можно открыть patches/ нижней кнопкой.",
                    "Sync from GitHub",
                    "ok",
                )
            return

        if latest.get("manifestError"):
            self._set_next_action(
                "build_plan",
                "Посмотреть ошибку патча",
                f"Найден patch.zip, но его манифест некорректен: {latest.get('manifestError')}. Постройте план, чтобы увидеть детали валидации.",
                "Показать ошибку патча",
                "bad",
            )
            return

        title = latest.get("title") or latest.get("name") or "следующий патч"
        upgrade_note = ""
        if upgrade_available:
            upgrade_note = f" Дополнительно devctl предлагает обновить структуру workspace: {upgrade_details}. Это не блокирует построение плана и запуск патча."
        self._set_next_action(
            "build_plan",
            "Построить прозрачный план запуска",
            f"Workspace выглядит готовым. Следующий патч: {title}. Перед запуском лучше посмотреть dry-run план: файлы, проверки, commit и push.{upgrade_note}",
            "Построить план",
            "ok",
        )

    def _recommend_from_plan(self, data: dict, result: RunResult) -> None:
        if not isinstance(data, dict) or not data:
            self._set_next_action(
                "refresh_status",
                "Не удалось разобрать план",
                result.stderr or result.stdout or "Команда plan не вернула JSON. Обновите статус и проверьте вкладку «План».",
                "Обновить статус",
                "bad",
            )
            return

        if not data.get("ok"):
            validation = data.get("validation") if isinstance(data.get("validation"), dict) else {}
            error = validation.get("error") or data.get("error") or "Патч не прошёл dry-run проверку."
            self._set_next_action(
                "open_patches",
                "Исправить или заменить patch.zip",
                f"План построить нельзя: {error} После исправления положите обновлённый архив в patches/ и нажмите «Обновить».",
                "Открыть patches/",
                "bad",
            )
            return

        patch = data.get("patch") if isinstance(data.get("patch"), dict) else {}
        manifest = data.get("manifest") if isinstance(data.get("manifest"), dict) else {}
        apply = data.get("apply") if isinstance(data.get("apply"), dict) else {}
        checks = data.get("checks") if isinstance(data.get("checks"), list) else []
        push = data.get("push") if isinstance(data.get("push"), dict) else {}

        patch_title = manifest.get("title") or patch.get("title") or patch.get("name") or "патч"
        push_text = "без push"
        if push.get("enabled"):
            push_text = f"push в {push.get('remote') or 'origin'}/{push.get('branch') or 'текущую ветку'}"
        self._set_next_action(
            "start_pipeline",
            f"Запустить конвейер для патча «{patch_title}»",
            "План готов: "
            f"файлов к копированию — {apply.get('copyCount', 0)}, "
            f"удалений — {apply.get('deleteCount', 0)}, "
            f"проверок — {len(checks)}, {push_text}. После нажатия devctl применит патч, выполнит проверки, сделает commit и при необходимости push.",
            "Запустить конвейер",
            "ok",
        )

    def _recommend_after_result(self, data: dict, result: RunResult) -> None:
        status = data.get("status") if isinstance(data, dict) else None
        if result.returncode == 0:
            uts_project = data.get("utsProjectDir") if isinstance(data, dict) else None
            if uts_project:
                self._set_next_action(
                    "open_uts",
                    "Открыть свежую UTS-копию",
                    f"Конвейер завершился со статусом {status or 'OK'}. Успешный post-снимок уже развёрнут для ручного тестирования: {uts_project}",
                    "Открыть UTS",
                    "ok",
                )
                return
            self._set_next_action(
                "open_report",
                "Открыть отчёт успешного запуска",
                f"Конвейер завершился со статусом {status or 'OK'}. Отчёт уже создан и содержит commit/push-сводку.",
                "Открыть отчёт",
                "ok",
            )
        else:
            self._set_next_action(
                "open_report",
                "Разобрать ошибку по отчёту",
                f"Конвейер остановился со статусом {status or 'ошибка'}. Откройте отчёт: там есть ошибки, предупреждения и путь к диагностическому архиву.",
                "Открыть отчёт",
                "bad",
            )

    def show_git_status(self) -> None:
        data = self.last_status or {}
        git = data.get("git", {}) if isinstance(data, dict) else {}
        workspace = data.get("workspace", {}) if isinstance(data, dict) else {}
        porcelain = git.get("porcelain") or git.get("statusShort") or ""
        lines = [
            "== git status ==",
            f"Project: {workspace.get('projectRoot') or 'неизвестно'}",
            f"Ветка: {git.get('branch') or 'неизвестно'}",
            "",
        ]
        if porcelain.strip():
            lines.append(porcelain.rstrip())
        else:
            lines.append("Локальные изменения не перечислены в status JSON. Откройте project/ и выполните git status вручную.")
        lines.extend([
            "",
            "Перед запуском devctl приведите рабочее дерево к чистому состоянию: закоммитьте нужное, уберите временное или откатите лишнее.",
        ])
        self.set_text(self.plan_text, "\n".join(lines) + "\n")
        self.notebook.select(0)

    def _current_output_widget(self) -> tuple[str, tk.Text]:
        selected = self.notebook.select()
        tabs = [
            ("План", self.plan_text),
            ("Запуск", self.run_text),
            ("Отчёт", self.report_text),
        ]
        for title, widget in tabs:
            if str(widget.master) == selected:
                return title, widget
        return "План", self.plan_text

    def copy_current_output(self) -> None:
        """Надёжно копирует весь текст активной вкладки вывода.

        Копирование выделения из disabled Text в Tkinter на Windows может вести
        себя нестабильно. Эта кнопка читает содержимое виджета напрямую и
        кладёт его в clipboard независимо от selection/focus/state.
        """
        title, widget = self._current_output_widget()
        text = widget.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo(APP_NAME, f"Во вкладке «{title}» пока нет текста для копирования.", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        messagebox.showinfo(APP_NAME, f"Текущий вывод вкладки «{title}» скопирован в буфер обмена.", parent=self)

    def copy_patch_prompt(self) -> None:
        """Копирует в буфер обмена шаблон запроса для новой ChatGPT-сессии."""
        text = PATCH_PROMPT_TEMPLATE.strip() + "\n"
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.set_text(
            self.report_text,
            "== prompt-шаблон devctl-патча ==\n\n"
            "Шаблон скопирован в буфер обмена. Его можно вставить в новую ChatGPT-сессию, "
            "чтобы попросить собрать корректный devctl-патч для этого workspace.\n\n"
            + text,
        )
        self.notebook.select(2)
        messagebox.showinfo(APP_NAME, "Prompt-шаблон для devctl-патча скопирован в буфер обмена.", parent=self)

    def choose_workspace(self) -> None:
        selected = filedialog.askdirectory(title="Выберите корень рабочей области devctl")
        if not selected:
            return
        self.workspace_var.set(selected)
        self._save_workspace()
        self.refresh_status()

    def init_workspace(self) -> None:
        current = Path(self.workspace_var.get()).expanduser()
        initial_parent = current.parent if current.name else Path.home()
        dialog = InitWorkspaceDialog(self, initial_parent=initial_parent)
        self.wait_window(dialog)
        request = dialog.result
        if not request:
            return

        parent = Path(request["parent"]).expanduser().resolve()
        workspace = (parent / request["name"]).resolve()
        remote_url = request.get("remoteUrl", "").strip()
        branch = request.get("branch", "main").strip() or "main"

        try:
            parent.mkdir(parents=True, exist_ok=True)
            if workspace.exists() and any(workspace.iterdir()):
                messagebox.showerror(
                    APP_NAME,
                    "Папка workspace уже существует и не пуста.\n\n"
                    f"{workspace}\n\n"
                    "Выберите другое название или пустую директорию, чтобы GUI ничего случайно не перезаписал.",
                )
                return
            workspace.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Не удалось подготовить папку workspace:\n{workspace}\n\n{exc}")
            return

        self.set_running(True)
        self.set_text(
            self.report_text,
            "Инициализирую workspace...\n\n"
            f"Workspace: {workspace}\n"
            f"Project:   {workspace / 'project'}\n"
            f"Remote:    {remote_url or 'не задан'}\n",
        )
        self.notebook.select(2)

        args = [
            "init",
            "--json",
            "--workspace", str(workspace),
            "--project", "project",
            "--patches", "patches",
            "--archives", "archives",
            "--uts", "UserTestSpace",
            "--create-project",
            "--git-init",
            "--branch", branch,
        ]
        if remote_url:
            args.extend(["--remote-url", remote_url])

        init_runner = DevctlRunner(workspace)
        self._run_async(
            args,
            lambda result, target=workspace: self._on_init_workspace_done(result, target),
            runner=init_runner,
            save_workspace=False,
        )

    def _on_init_workspace_done(self, result: RunResult, workspace: Path) -> None:
        self.set_running(False)
        data = result.json_data or {}
        self.set_text(self.report_text, self._format_init_result(data if isinstance(data, dict) else {}, result, workspace))
        if result.ok and isinstance(data, dict) and data.get("ok"):
            self.workspace_var.set(str(workspace))
            self._save_workspace()
            self.last_report_path = None
            self.last_archive_path = None
            self.refresh_status()
            messagebox.showinfo(APP_NAME, "Workspace создан и открыт в GUI.")
        else:
            messagebox.showerror(APP_NAME, "Инициализация workspace завершилась с ошибкой. Подробности во вкладке «Отчёт».")

    def _format_init_result(self, data: dict, result: RunResult, workspace: Path) -> str:
        if not data:
            return (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        git_data = data.get("git") if isinstance(data.get("git"), dict) else {}
        lines = [
            "== инициализация workspace ==",
            f"Статус: {'OK' if data.get('ok') else 'ошибка'}",
            f"Код возврата: {result.returncode}",
            f"Workspace: {data.get('workspaceRoot') or workspace}",
            f"Project: {data.get('projectRoot') or workspace / 'project'}",
            f"Patches: {data.get('patchesDir') or workspace / 'patches'}",
            f"Archives: {data.get('archivesDir') or workspace / 'archives'}",
            f"UTS: {data.get('userTestSpaceDir') or workspace / 'UserTestSpace'}",
            f"Config: {data.get('configPath') or workspace / '.devctl' / 'workspace.json'}",
            "",
            "== git ==",
            f"Git доступен: {git_data.get('available')}",
            f"Репозиторий создан: {git_data.get('initialized')}",
            f"Ветка: {git_data.get('branch') or 'неизвестно'}",
            f"Remote origin: {git_data.get('remoteUrl') or 'не задан'}",
            f"Remote связан: {git_data.get('remoteLinked')}",
            f"Операция: {git_data.get('operation') or 'нет'}",
            f"Синхронизация remote: {git_data.get('synced')}",
            f"Pull выполнен: {git_data.get('pulled')}",
            f"Pull пропущен: {git_data.get('pullSkipped')}",
            "",
            "== создано ==",
        ]
        created = data.get("created") or []
        lines.extend([f"- {item}" for item in created] or ["всё уже существовало"])
        operations = git_data.get("operations") if isinstance(git_data, dict) else []
        lines.append("")
        lines.append("== git-шаги ==")
        lines.extend([f"- {item}" for item in operations] or ["нет"])
        warnings = data.get("warnings") or []
        lines.append("")
        lines.append("== предупреждения ==")
        lines.extend([f"- {item}" for item in warnings] or ["нет"])
        errors = []
        if data.get("error"):
            errors.append(data.get("error"))
        if isinstance(git_data, dict):
            errors.extend(git_data.get("errors") or [])
        lines.append("")
        lines.append("== ошибки ==")
        lines.extend([f"- {item}" for item in errors] or ["нет"])
        return "\n".join(lines) + "\n"

    def sync_workspace(self) -> None:
        self._save_workspace()
        proceed = messagebox.askyesno(
            APP_NAME,
            "Синхронизировать workspace с GitHub как источником истины?\n\n"
            "GUI вызовет `devctl sync --discard-local --json`: project/ будет приведён к origin/ветке через fetch + reset --hard + git clean, затем devctl создаст свежий архив в archives/ и развернёт копию в UserTestSpace/.\n\n"
            "Локальные незакоммиченные изменения и локальные commit'ы, которых нет в remote, могут быть отброшены.",
            parent=self,
        )
        if not proceed:
            return
        self.set_running(True)
        self.set_text(
            self.report_text,
            "Синхронизирую workspace с GitHub как источником истины...\n\n"
            "Команда: devctl sync --discard-local --json\n"
            "Этапы: fetch/reset/clean -> свежий archives/ snapshot -> свежий UserTestSpace/.\n",
        )
        self.notebook.select(2)
        self._run_async(["sync", "--discard-local", "--json"], self._on_sync_workspace_done, timeout=900)

    def _on_sync_workspace_done(self, result: RunResult) -> None:
        self.set_running(False)
        data = result.json_data or {}
        if isinstance(data, dict):
            archive = data.get("archive") if isinstance(data.get("archive"), dict) else {}
            uts = data.get("uts") if isinstance(data.get("uts"), dict) else {}
            self.last_archive_path = archive.get("path") or self.last_archive_path
            self.last_uts_path = uts.get("projectDir") or self.last_uts_path
            self.set_text(self.report_text, self._format_sync_result(data, result))
        else:
            self.set_text(self.report_text, result.stdout + ("\n" + result.stderr if result.stderr else ""))
        self.notebook.select(2)
        self.refresh_status()
        if result.ok and isinstance(data, dict) and data.get("ok"):
            messagebox.showinfo(APP_NAME, "Workspace синхронизирован: project, archives и UserTestSpace актуализированы.", parent=self)
        else:
            messagebox.showerror(APP_NAME, "Не удалось синхронизировать workspace. Подробности во вкладке «Отчёт».", parent=self)

    def _format_sync_result(self, data: dict, result: RunResult) -> str:
        if not data:
            return (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        workspace = data.get("workspace") if isinstance(data.get("workspace"), dict) else {}
        git = data.get("git") if isinstance(data.get("git"), dict) else {}
        archive = data.get("archive") if isinstance(data.get("archive"), dict) else {}
        uts = data.get("uts") if isinstance(data.get("uts"), dict) else {}
        lines = [
            "== sync workspace ==",
            f"Статус: {'OK' if data.get('ok') else 'ошибка'}",
            f"Код возврата: {result.returncode}",
            f"Workspace: {workspace.get('workspaceRoot') or 'неизвестно'}",
            f"Project: {workspace.get('projectRoot') or 'неизвестно'}",
            "",
            "== git ==",
            f"Remote: {git.get('remote') or 'origin'}",
            f"Remote URL: {git.get('remoteUrl') or 'не задан'}",
            f"Ветка: {git.get('branch') or 'неизвестно'}",
            f"Discard local: {git.get('discardLocal')}",
            f"Head after: {git.get('headAfter') or 'нет'}",
            f"Clean after: {git.get('cleanAfter')}",
            "",
            "== git-шаги ==",
        ]
        operations = git.get("operations") or []
        lines.extend([f"- {item}" for item in operations] or ["нет"])
        lines.extend([
            "",
            "== archives / UTS ==",
            f"Архив: {archive.get('path') or 'не создавался'}",
            f"Файлов в архиве: {archive.get('fileCount', 0)}",
            f"UTS project: {uts.get('projectDir') or 'не обновлялся'}",
            "",
            "== создано ==",
        ])
        created = data.get("created") or []
        lines.extend([f"- {item}" for item in created] or ["служебные папки уже существовали"])
        warnings = []
        warnings.extend(data.get("warnings") or [])
        warnings.extend(git.get("warnings") or [])
        lines.append("")
        lines.append("== предупреждения ==")
        lines.extend([f"- {item}" for item in warnings] or ["нет"])
        errors = []
        if data.get("error"):
            errors.append(data.get("error"))
        errors.extend(git.get("errors") or [])
        lines.append("")
        lines.append("== ошибки ==")
        lines.extend([f"- {item}" for item in errors] or ["нет"])
        return "\n".join(lines) + "\n"

    def upgrade_workspace(self) -> None:
        self._save_workspace()
        proceed = messagebox.askyesno(
            APP_NAME,
            "Безопасно обновить структуру workspace?\n\n"
            "GUI вызовет `devctl init --upgrade`: команда добавляет недостающие поля конфигурации и служебные папки вроде UserTestSpace/, но не трогает содержимое project/.",
            parent=self,
        )
        if not proceed:
            return
        self.set_running(True)
        self.set_text(self.report_text, "Обновляю структуру workspace через devctl init --upgrade...\n")
        self.notebook.select(2)
        self._run_async(["init", "--upgrade", "--json", "--workspace", self.workspace_var.get()], self._on_upgrade_workspace_done)

    def _on_upgrade_workspace_done(self, result: RunResult) -> None:
        self.set_running(False)
        data = result.json_data or {}
        self.set_text(self.report_text, self._format_upgrade_result(data if isinstance(data, dict) else {}, result))
        self.notebook.select(2)
        self.refresh_status()
        if result.ok and isinstance(data, dict) and data.get("ok"):
            messagebox.showinfo(APP_NAME, "Структура workspace обновлена.", parent=self)
        else:
            messagebox.showerror(APP_NAME, "Не удалось обновить структуру workspace. Подробности во вкладке «Отчёт».", parent=self)

    def _format_upgrade_result(self, data: dict, result: RunResult) -> str:
        if not data:
            return (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        lines = [
            "== обновление структуры workspace ==",
            f"Статус: {'OK' if data.get('ok') else 'ошибка'}",
            f"Код возврата: {result.returncode}",
            f"Workspace: {data.get('workspaceRoot')}",
            f"Config: {data.get('configPath')}",
            f"Config изменён: {data.get('changed')}",
            "",
            "== создано ==",
        ]
        lines.extend([f"- {item}" for item in data.get("created") or []] or ["ничего"])
        lines.append("")
        lines.append("== обновлённые поля/исключения ==")
        lines.extend([f"- {item}" for item in data.get("updatedFields") or []] or ["уже актуально"])
        warnings = data.get("warnings") or []
        lines.append("")
        lines.append("== предупреждения ==")
        lines.extend([f"- {item}" for item in warnings] or ["нет"])
        if data.get("error"):
            lines.extend(["", "== ошибка ==", str(data.get("error"))])
        return "\n".join(lines) + "\n"

    def reset_project(self) -> None:
        self._save_workspace()
        proceed = messagebox.askyesno(
            APP_NAME,
            "Откатить project/?\n\n"
            "Будет выполнен `devctl reset`: git reset --hard HEAD и git clean -fd. "
            "Локальные незакоммиченные изменения и untracked-файлы в project/ будут удалены.",
            parent=self,
        )
        if not proceed:
            return
        self.set_running(True)
        self.set_text(self.report_text, "Выполняю devctl reset...\n")
        self.notebook.select(2)
        self._run_async(["reset", "--json"], self._on_reset_done)

    def _on_reset_done(self, result: RunResult) -> None:
        self.set_running(False)
        data = result.json_data or {}
        self.set_text(self.report_text, self._format_reset_result(data if isinstance(data, dict) else {}, result))
        self.notebook.select(2)
        self.refresh_status()
        if result.ok and isinstance(data, dict) and data.get("ok"):
            messagebox.showinfo(APP_NAME, "project/ откатан и очищен.", parent=self)
        else:
            messagebox.showerror(APP_NAME, "devctl reset завершился с ошибкой. Подробности во вкладке «Отчёт».", parent=self)

    def _format_reset_result(self, data: dict, result: RunResult) -> str:
        if not data:
            return (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        lines = [
            "== reset project ==",
            f"Статус: {'OK' if data.get('ok') else 'ошибка'}",
            f"Код возврата: {result.returncode}",
            f"Project: {data.get('projectRoot')}",
            f"Target: {data.get('target')}",
            f"Clean mode: {data.get('cleanMode')}",
            f"Patch удалён: {data.get('patchDeleted') or 'нет'}",
            "",
            "== git status before ==",
            data.get("gitStatusBefore") or "clean/нет данных",
            "",
            "== git status after ==",
            data.get("gitStatusAfter") or "clean",
        ]
        if data.get("error"):
            lines.extend(["", "== ошибка ==", str(data.get("error"))])
        return "\n".join(str(item) for item in lines) + "\n"

    def _save_workspace(self) -> None:
        workspace = str(Path(self.workspace_var.get()).expanduser().resolve())
        if not looks_like_pyinstaller_temp(Path(workspace)):
            self.config_data["lastWorkspace"] = workspace
            save_config(self.config_data)
        self.runner.set_workspace(workspace)

    def _run_async(self, args: list[str], callback, *, runner: DevctlRunner | None = None, save_workspace: bool = True, timeout: int = 180) -> None:
        if save_workspace:
            self._save_workspace()
        active_runner = runner or self.runner

        def worker() -> None:
            result = active_runner.run(args, timeout=timeout)
            self.events.put(("result", (callback, result)))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_status(self) -> None:
        self.set_text(self.plan_text, "Обновляю статус...\n")
        self._run_async(["status", "--json"], self._on_status)

    def build_plan(self) -> None:
        self.set_text(self.plan_text, "Строю dry-run план...\n")
        self._run_async(["plan", "--json"], self._on_plan)

    def _on_status(self, result: RunResult) -> None:
        data = result.json_data or {}
        self.last_status = data if isinstance(data, dict) else None
        if not data.get("ok"):
            text = result.stderr or result.stdout or data.get("error") or "Не удалось получить статус."
            self.cards["project"].set("ошибка", "bad")
            self.cards["git"].set("недоступно", "bad")
            self.cards["patch"].set("неизвестно", "warn")
            self.cards["uts"].set("неизвестно", "warn")
            self.cards["push"].set("неизвестно", "warn")
            self._set_next_action(
                "choose_workspace",
                "Выбрать корректную рабочую область",
                str(text),
                "Выбрать workspace",
                "bad",
            )
            self.set_text(self.plan_text, text)
            return
        workspace = data.get("workspace", {})
        git = data.get("git", {})
        latest = (data.get("patches", {}) or {}).get("latest")
        self.cards["project"].set("найден" if workspace.get("projectExists") else "не найден", "ok" if workspace.get("projectExists") else "bad")
        if not git.get("available"):
            self.cards["git"].set("git не найден", "bad")
        elif not git.get("isRepository"):
            self.cards["git"].set("не репозиторий", "bad")
        else:
            self.cards["git"].set("чисто" if git.get("clean") else "есть изменения", "ok" if git.get("clean") else "warn")
        if latest:
            kind = "bad" if latest.get("manifestError") else "ok"
            self.cards["patch"].set(latest.get("title") or latest.get("name") or "найден", kind)
        else:
            patches = data.get("patches", {}) if isinstance(data.get("patches"), dict) else {}
            if patches.get("count"):
                self.cards["patch"].set("нет новых", "ok")
            else:
                self.cards["patch"].set("нет патчей", "warn")
        if workspace.get("userTestSpaceDirExists"):
            self.cards["uts"].set("готов", "ok")
        else:
            self.cards["uts"].set("нужно обновить", "warn")
        self.cards["push"].set("см. план" if latest else "неизвестно", "neutral")
        self._recommend_from_status(data)
        self.set_text(self.plan_text, self._format_status(data))

    def _on_plan(self, result: RunResult) -> None:
        data = result.json_data or {}
        self.last_plan = data if isinstance(data, dict) else None
        self.set_text(self.plan_text, self._format_plan(data, result))
        push = data.get("push") if isinstance(data, dict) else None
        if isinstance(push, dict):
            enabled = bool(push.get("enabled"))
            target = f"{push.get('remote')}/{push.get('branch')}" if push.get("remote") and push.get("branch") else "цель неизвестна"
            self.cards["push"].set(("будет выполнен: " if enabled else "отключён: ") + target, "ok" if enabled else "warn")
        self._recommend_from_plan(data, result)
        self.notebook.select(0)

    def _format_status(self, data: dict) -> str:
        workspace = data.get("workspace", {})
        git = data.get("git", {})
        patches = data.get("patches", {})
        lines = [
            "== статус devctl GUI ==",
            f"devctl: v{data.get('version')}",
            f"Рабочая область: {workspace.get('workspaceRoot')}",
            f"Проект: {workspace.get('projectRoot')}",
            f"Патчи: {workspace.get('patchesDir')}",
            f"Архивы: {workspace.get('archivesDir')}",
            f"UTS: {workspace.get('userTestSpaceDir')} ({'есть' if workspace.get('userTestSpaceDirExists') else 'нет'})",
            "",
            "== конфигурация workspace ==",
        ]
        workspace_config = data.get("workspaceConfig", {}) if isinstance(data.get("workspaceConfig"), dict) else {}
        lines.extend([
            f"Требует обновления: {workspace_config.get('upgradeAvailable')}",
            f"Недостающие поля: {', '.join(str(x) for x in workspace_config.get('missingFields') or []) or 'нет'}",
            f"Недостающие исключения archive: {', '.join(str(x) for x in workspace_config.get('missingArchiveExcludes') or []) or 'нет'}",
            f"Недостающие директории: {', '.join(str(x) for x in workspace_config.get('missingDirs') or []) or 'нет'}",
            "",
            "== git ==",
            f"Доступен: {git.get('available')}",
            f"Репозиторий: {git.get('isRepository')}",
            f"Ветка: {git.get('branch') or 'неизвестно'}",
            f"Рабочее дерево: {'чистое' if git.get('clean') else 'есть изменения/неизвестно'}",
            f"Remote origin: {git.get('remoteUrl') or 'не задан'}",
            f"Ahead/behind: {((git.get('aheadBehind') or {}).get('ahead'))}/{((git.get('aheadBehind') or {}).get('behind'))}",
            f"Ошибка: {git.get('error') or 'нет'}",
            "",
            "== патчи ==",
            f"Всего кандидатов: {patches.get('count', 0)}",
        ])
        latest = patches.get("latest")
        if latest:
            lines.extend([
                f"Последний кандидат: {latest.get('name')}",
                f"ID: {latest.get('patchId') or 'неизвестно'}",
                f"Название: {latest.get('title') or 'неизвестно'}",
                f"Статус: {latest.get('status')}",
                f"Манифест: {latest.get('manifestError') or 'OK'}",
            ])
        else:
            if patches.get("count"):
                lines.append("Неприменённых patch.zip не найдено; все кандидаты уже применены или видны в Git-трейлерах.")
            else:
                lines.append("Zip-файлы патчей не найдены.")
        return "\n".join(lines) + "\n"

    def _format_plan(self, data: dict, result: RunResult) -> str:
        if not isinstance(data, dict) or not data:
            return (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        lines = ["== dry-run план =="]
        if not data.get("ok"):
            lines.append("План содержит ошибку или патч некорректен.")
            validation = data.get("validation") or {}
            if validation.get("error"):
                lines.append(f"Ошибка валидации: {validation.get('error')}")
            elif data.get("error"):
                lines.append(f"Ошибка: {data.get('error')}")
        patch = data.get("patch") or {}
        manifest = data.get("manifest") or {}
        if patch:
            lines.extend([
                "",
                "== патч ==",
                f"Файл: {patch.get('name')}",
                f"ID: {manifest.get('patchId') or patch.get('patchId') or 'неизвестно'}",
                f"Название: {manifest.get('title') or patch.get('title') or 'неизвестно'}",
                f"SHA-256: {patch.get('sha256') or 'неизвестно'}",
                f"Сводка: {manifest.get('summary') or ''}",
            ])
        apply = data.get("apply") or {}
        lines.extend([
            "",
            "== применение ==",
            f"Корень файлов: {apply.get('filesRoot') or 'files'}",
            f"Файлов к копированию: {apply.get('copyCount', 0)}",
        ])
        for name in (apply.get("copyFiles") or [])[:120]:
            lines.append(f"  + {name}")
        if len(apply.get("copyFiles") or []) > 120:
            lines.append("  ...")
        lines.append(f"Путей к удалению: {apply.get('deleteCount', 0)}")
        for entry in (apply.get("deletePaths") or [])[:120]:
            lines.append(f"  - {entry.get('path')} recursive={entry.get('recursive', False)} required={entry.get('required', False)}")
        lines.append("")
        lines.append("== проверки ==")
        checks = data.get("checks") or []
        if checks:
            for check in checks:
                lines.append(f"  - {check.get('name')}: {check.get('command')} [cwd={check.get('cwd')}]")
        else:
            lines.append("Проверки не объявлены.")
        commit = data.get("commit") or {}
        push = data.get("push") or {}
        lines.extend([
            "",
            "== commit / push ==",
            "Политика: проверки -> commit -> push",
            f"Сообщение коммита: {commit.get('message') or ''}",
            f"Push включён: {push.get('enabled')}",
            f"Цель push: {push.get('remote')}/{push.get('branch')}",
            f"Примечание: {push.get('note') or ''}",
            "",
            "Файлы не изменялись. Для выполнения нажмите «Запустить конвейер»."
        ])
        return "\n".join(lines) + "\n"

    def start_pipeline(self, no_push: bool) -> None:
        self._save_workspace()
        plan = self.last_plan
        if not plan or not plan.get("patch"):
            self.build_plan()
            proceed = messagebox.askyesno(
                APP_NAME,
                "План обновляется. Запустить конвейер после текущей проверки лучше вручную. Всё равно запустить сейчас?",
                parent=self,
            )
            if not proceed:
                return
        else:
            patch = plan.get("patch", {})
            push = plan.get("push", {})
            target = f"{push.get('remote')}/{push.get('branch')}" if push else "неизвестно"
            message = [
                f"Патч: {patch.get('title') or patch.get('name')}",
                f"Файл: {patch.get('name')}",
                f"Push: {'отключён вручную' if no_push else target}",
                "",
                "Запустить конвейер сейчас?",
            ]
            if not messagebox.askyesno("Подтверждение запуска", "\n".join(message), parent=self):
                return
        self.set_running(True)
        self.set_text(self.run_text, "")
        self.notebook.select(1)
        args = ["start", "--json"]
        if no_push:
            args.append("--no-push")

        def on_line(line: str) -> None:
            self.events.put(("line", line))

        def on_done(result: RunResult) -> None:
            self.events.put(("done", result))

        self.runner.stream(args, on_line, on_done)

    def set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for widget in (self.main_button, self.start_btn, self.no_push_btn, self.status_btn, self.sync_btn, self.plan_btn, self.init_btn, self.init_top_btn, self.upgrade_btn, self.reset_btn, self.report_btn, self.archives_btn, self.uts_btn, self.project_btn, self.copy_output_btn, self.copy_prompt_btn):
            widget.configure(state=state)

    def _on_start_done(self, result: RunResult) -> None:
        self.set_running(False)
        data = result.json_data or {}
        if isinstance(data, dict):
            self.last_report_path = data.get("reportPath") or self.last_report_path
            self.last_archive_path = data.get("archivePath") or self.last_archive_path
            self.last_uts_path = data.get("utsProjectDir") or self.last_uts_path
            self.set_text(self.report_text, self._format_result(data, result))
            self._recommend_after_result(data, result)
        else:
            self.set_text(self.report_text, result.stdout + ("\n" + result.stderr if result.stderr else ""))
            self._set_next_action(
                "refresh_status",
                "Проверить состояние после запуска",
                "Конвейер завершился без машинно-читаемого JSON. Обновите статус и проверьте лог запуска.",
                "Обновить статус",
                "warn",
            )
        self.notebook.select(2)
        self.refresh_status()
        if result.returncode == 0:
            messagebox.showinfo(APP_NAME, "Конвейер завершён успешно.")
        else:
            messagebox.showerror(APP_NAME, "Конвейер завершился с ошибкой. Подробности во вкладке «Отчёт» и в логах запуска.")

    def _format_result(self, data: dict, result: RunResult) -> str:
        lines = [
            "== результат запуска ==",
            f"Статус: {data.get('status')}",
            f"Код возврата: {data.get('returncode', result.returncode)}",
            f"Отчёт: {data.get('reportPath') or 'нет'}",
            f"Каталог архива: {data.get('archivePath') or 'нет'}",
            f"Коммит: {data.get('commitSha') or 'нет'}",
            f"Push: {data.get('pushResult') or 'нет'}",
            f"Auto-reset: {data.get('autoResetPerformed')}",
            f"Удалённый bad patch: {data.get('badPatchDeleted') or 'нет'}",
            f"UTS project: {data.get('utsProjectDir') or 'нет'}",
            f"Bytecode очищено: {len(data.get('cleanedBytecodePaths') or [])}",
            "",
            "== предупреждения ==",
        ]
        warnings = data.get("warnings") or []
        lines.extend([f"- {item}" for item in warnings] or ["нет"])
        lines.append("")
        lines.append("== ошибки ==")
        errors = data.get("errors") or []
        lines.extend([f"- {item}" for item in errors] or ["нет"])
        return "\n".join(lines) + "\n"

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "result":
                    callback, result = payload  # type: ignore[misc]
                    callback(result)
                elif kind == "line":
                    self.append_run(str(payload))
                elif kind == "done":
                    self._on_start_done(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def open_report(self) -> None:
        open_path(self.last_report_path)

    def open_archives(self) -> None:
        if self.last_archive_path:
            open_path(self.last_archive_path)
            return
        data = self.last_status or {}
        workspace = data.get("workspace", {}) if isinstance(data, dict) else {}
        open_path(workspace.get("archivesDir"))

    def open_patches(self) -> None:
        data = self.last_status or {}
        workspace = data.get("workspace", {}) if isinstance(data, dict) else {}
        open_path(workspace.get("patchesDir"))

    def open_uts(self) -> None:
        if self.last_uts_path:
            open_path(self.last_uts_path)
            return
        data = self.last_status or {}
        workspace = data.get("workspace", {}) if isinstance(data, dict) else {}
        open_path(workspace.get("userTestSpaceDir"))

    def open_project(self) -> None:
        data = self.last_status or {}
        workspace = data.get("workspace", {}) if isinstance(data, dict) else {}
        open_path(workspace.get("projectRoot"))


def main() -> int:
    configure_standard_streams()
    if len(sys.argv) > 1 and sys.argv[1] == "--devctl-child":
        return run_devctl_child(sys.argv[2:])
    app = DevctlGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
