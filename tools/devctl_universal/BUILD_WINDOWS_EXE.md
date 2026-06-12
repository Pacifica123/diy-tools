# Сборка `devctl-gui.exe` на Windows

## Требования

- Windows 10/11.
- Python 3.11+ с включённым `tkinter`.
- Git for Windows, если нужен реальный `commit/push` из конвейера.

## Команды сборки

Откройте PowerShell именно в папке `project`, где лежат `devctl.py`, `gui/` и `build/`, и выполните:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip pyinstaller
pyinstaller build\pyinstaller.spec --clean --noconfirm
```

Альтернативно можно запустить готовый скрипт из этой же папки:

```powershell
.\build_exe.ps1
```

Скрипт `build_exe.ps1` намеренно оставлен ASCII-only, чтобы Windows PowerShell 5 не ломался на UTF-8 без BOM.

Spec-файл сам находит корень проекта относительно `project/build/pyinstaller.spec`, поэтому кириллица и пробелы в пути допустимы. После успешной сборки файл будет здесь:

```text
release/devctl-gui.exe
```

## Проверка EXE

```powershell
.\release\devctl-gui.exe
```

В окне GUI:

1. Для новой рабочей области нажмите `Новый workspace`, выберите родительскую папку, имя workspace и при необходимости вставьте GitHub/Git remote URL.
2. Для существующей рабочей области выберите корень workspace кнопкой `Выбрать`.
3. Нажмите `Показать статус`.
4. Нажмите `Построить план`.
5. Для безопасного smoke-теста используйте `Запустить без push`.
6. После завершения откройте отчёт кнопкой `Открыть отчёт`.

## CLI smoke-тесты перед сборкой

```powershell
python -m py_compile devctl.py gui\devctl_runner.py gui\devctl_gui.py
python devctl.py --help
python devctl.py status --json
python devctl.py plan --json
python gui\devctl_gui.py --devctl-child . status --json
python gui\devctl_gui.py --devctl-child . init --json --workspace .tmp-init-smoke --create-project --git-init --branch main
```

## Как устроен bundled child-mode

GUI запускает `devctl.py` в отдельном процессе. В исходниках это обычный subprocess через текущий Python. В собранном PyInstaller `.exe` GUI запускает сам себя с внутренним флагом:

```text
devctl-gui.exe --devctl-child <workspace> <devctl args...>
```

В этом режиме приложение импортирует bundled `devctl.py`, меняет текущий каталог на рабочую область и выполняет CLI-команду. Поэтому GUI остаётся отзывчивым, live-лог работает, а отдельный Python на пользовательской машине для GUI не требуется. Для Git-операций нужен установленный Git.

## Диагностика частых проблем

- В поле рабочей области показан путь вида `C:\Users\...\Temp\_MEI...`: это временная папка PyInstaller из старой сборки. В новой сборке такой путь игнорируется. Если он уже успел сохраниться, выберите нормальную рабочую область кнопкой `Выбрать` или удалите `%APPDATA%\devctl-gui\config.json`.
- В окне видны символы `����` вместо русского текста: это была проблема кодировки child-процесса на Windows. В новой сборке GUI принудительно запускает дочерний процесс с `PYTHONUTF8=1` и `PYTHONIOENCODING=utf-8`.
- `git не найден`: установите Git for Windows и проверьте PATH.
- `корень проекта не является репозиторием Git`: проверьте `projectDir` в `.devctl/workspace.json`.
- `Рабочее дерево Git не чистое`: закоммитьте, спрячьте или отмените локальные изменения перед запуском.
- `Remote-ссылка origin/<branch> не найдена`: для новых пустых remote новая версия не валит preflight заранее и позволит первому push создать ветку. Если ошибка всё равно появилась, проверьте URL, права доступа и наличие GitHub-репозитория.
- При инициализации с GitHub URL GUI только связывает `origin`; авторизация для будущего push остаётся задачей Git/Git Credential Manager.
- `Author identity unknown` при первом commit: настройте Git identity, например `git config --global user.name "Ваше имя"` и `git config --global user.email "you@example.com"`.
