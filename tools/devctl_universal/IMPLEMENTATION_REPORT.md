# Отчёт реализации Windows GUI/EXE для devctl

## Реализовано


### Фича v0.1.3: Следующее лучшее действие в GUI

- Добавлен UX-блок `Следующее действие` между карточками состояния и главной кнопкой.
- Центральная кнопка стала контекстной: она выполняет рекомендованное действие, а не всегда пытается запускать конвейер.
- Статус workspace теперь преобразуется в понятные сценарии: создать workspace, открыть `patches/`, показать `git status`, построить план, открыть отчёт.
- После успешного `plan --json` GUI предлагает запуск конвейера и показывает краткую сводку: число файлов, удалений, проверок и цель push.
- После завершения `start --json` GUI предлагает открыть отчёт успешного или ошибочного запуска.
- Добавлена кнопочная команда `open_patches()` и вывод `git status` во вкладку `План` без запуска терминала.


### Фича v0.1.2: init workspace из GUI

- Добавлена кнопка `Новый workspace` в верхней панели и `Инициализировать workspace` в нижней панели действий.
- Добавлен modal-dialog, который спрашивает родительскую директорию, имя workspace, optional Git remote URL и ветку.
- GUI создаёт папку workspace, запускает bundled `devctl init --json`, затем автоматически открывает созданный workspace.
- `devctl init` расширен флагами `--json`, `--create-project`, `--git-init`, `--branch`, `--remote-url`.
- Новый init создаёт `.devctl/workspace.json`, `.devctl/state.json`, `project/`, `patches/`, `archives/`, локальный Git-репозиторий в `project/` и optional `origin`.
- `git_branch()` стал устойчивым к пустому unborn-репозиторию через fallback на `git symbolic-ref --short HEAD`.
- Git preflight разрешает ситуацию, когда remote-ветка ещё не существует: первый успешный push сможет создать ветку.

### Исправления v0.1.1

- Исправлен стартовый путь в frozen/PyInstaller-сборке: GUI больше не использует временную папку `_MEI...` как рабочую область.
- Старый сохранённый `_MEI...` в `%APPDATA%\devctl-gui\config.json` теперь автоматически игнорируется.
- Исправлена кодировка Windows child-процесса: JSON и live-лог читаются как UTF-8 без `����`.
- `build_exe.ps1` сделан ASCII-only, чтобы Windows PowerShell не падал на UTF-8 без BOM.


### Этап 1. CLI готов к GUI

- Добавлен `--json` для `status`, `inspect`, `plan`.
- Добавлен `start --json`: в конце запуска печатается финальная JSON-строка с полями `status`, `reportPath`, `archivePath`, `commitSha`, `pushResult`, `errors`, `warnings`.
- Человекочитаемый русскоязычный вывод сохранён по умолчанию.

### Этапы 2–4. GUI MVP и UX

- Добавлены `gui/devctl_gui.py` и `gui/devctl_runner.py`.
- GUI реализован на `tkinter` без внешних runtime-зависимостей.
- Есть выбор рабочей области, запоминание последнего пути, кнопки `Статус`, `План`, `Запустить конвейер`, `Запустить без push`.
- Есть карточки состояния `Проект`, `Git`, `Патч`, `Push`.
- Есть вкладки `План`, `Запуск`, `Отчёт`.
- Запуск `start` идёт в отдельном subprocess/thread, окно не зависает.
- Live-лог стримится во вкладку `Запуск`.
- После запуска показываются путь к отчёту, каталог архива, SHA коммита и результат push.
- Добавлены кнопки открытия `report.md`, `archives/`, `project/`.

### Этап 5. Подготовка EXE

- Добавлен `build/pyinstaller.spec`.
- Добавлена иконка `gui/assets/icon.ico`.
- Добавлен bundled child-mode `--devctl-child`, чтобы собранный `.exe` мог запускать `devctl.py` как дочерний процесс без внешнего Python-интерпретатора.
- Добавлены инструкции: `BUILD_WINDOWS_EXE.md` и `gui/README_GUI.md`.

## Проверки, выполненные в этой среде

```bash
python3 -m py_compile devctl.py gui/devctl_runner.py gui/devctl_gui.py
python3 devctl.py --help
python3 devctl.py status --json
python3 devctl.py plan --json
python3 gui/devctl_gui.py --devctl-child . status --json
python3 gui/devctl_gui.py --devctl-child /tmp/ws init --json --workspace /tmp/ws --create-project --git-init --branch main
```

Также выполнен smoke-тест на временной рабочей области с Git-репозиторием, тестовым zip-патчем и запуском:

```bash
python3 devctl.py start --json --no-push
```

Результат smoke-теста: `status=applied`, отчёт создан, commit создан, push пропущен из-за `--no-push`.

## Что не выполнялось здесь

Windows `.exe` не собран в этой Linux-среде, потому что PyInstaller собирает Windows-бинарник корректно на Windows-хосте или в Windows VM. Проект полностью подготовлен к сборке: `build/pyinstaller.spec`, иконка, bundled child-mode и инструкции включены.


## v0.1.4: clickfix для запуска конвейера

После пользовательской проверки обнаружено, что кнопка `Запустить конвейер` могла выглядеть нерабочей после построения плана. Корневая причина: в `start_pipeline()` диалог `messagebox.askyesno` вызывался с третьим позиционным аргументом, что в Tkinter приводит к `TypeError`. В `.exe` это выглядело как отсутствие реакции на клик, потому что traceback уходил в невидимую консоль.

Исправления:

- вызов подтверждения запуска переведён на корректную форму `messagebox.askyesno(title, message, parent=self)`;
- добавлен `report_callback_exception()`, чтобы будущие ошибки GUI-callback отображались во вкладке `Отчёт` и показывались пользователю через messagebox;
- версия GUI обновлена до `0.1.4`.

## v0.1.5: prompt-шаблон для сборки devctl-патчей

Добавлен промежуточный UX-инструмент перед полноценным Patch Builder:

- в нижнюю панель GUI добавлена кнопка `Скопировать prompt-патча`;
- кнопка копирует в буфер обмена готовый текст запроса для новой ChatGPT-сессии;
- шаблон объясняет, что нужно вернуть именно `devctl`-патч, а не полный архив проекта;
- внутри шаблона описаны структура `patch.zip`, правила для `files/`, минимальный `manifest.json`, рекомендации по проверкам и формат финального ответа;
- текстовый вариант шаблона добавлен в `docs/agent/devctl-patch-prompt-template.md`.

Это небольшой костыль до отдельного автосборщика патчей, но он снижает вероятность неверной упаковки и помогает быстро выдавать нейросети одинаковый контракт на создание патча.
