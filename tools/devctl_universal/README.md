# devctl universal

Статус: `working`  
Зрелость: `M3`  
Флаги: `D, O, P, G`  
Основной интерфейс: `cli`, дополнительный интерфейс: `gui`

## Что делает

`devctl` — универсальный конвейер применения devctl-патчей: `plan -> start -> checks -> commit -> archive -> UserTestSpace`. GUI является тонкой оболочкой над тем же `devctl.py`.

## Когда использовать

Когда изменения проекта должны приходить не хаотичными ручными правками, а проверяемыми `patch.zip` с manifest, files root, checks и summary.

## Быстрый запуск

CLI:

```bash
python devctl.py --version
python devctl.py status
python devctl.py plan
python devctl.py start --no-push
```

GUI из исходников:

```bash
python gui/devctl_gui.py
```

Linux install как user-команда:

```bash
python3 devctl.py self install --with-completions
```

## Вход

Workspace с `.devctl/workspace.json`, каталогом `project/`, входящими `patches/` и архивами `archives/`. Основной вход — `patch_YYYYMMDD_HHMMSS_slug.zip` с `manifest.json`, `files/`, `PATCH_SUMMARY.md`.

## Выход

Применённые изменения в `project/`, Git commit/push по политике workspace, pre/post/failed archives, отчёты запусков и свежая копия в `UserTestSpace/`.

## Побочные эффекты и предупреждения

- Удаляет/меняет файлы: да, внутри целевого `project/` согласно patch manifest и reset-командам.
- Перезаписывает файлы: да, применяет payload из `files/`.
- Использует сеть: только через Git push/remote по настройке workspace.
- Запускает внешние команды: да, команды checks и Git.
- Может содержать приватные данные: да, archives/reports могут содержать код, пути, сообщения проверок.

Флаги `D/O/P/G` стоят намеренно: инструмент применяет generated patch payload, запускает проверки и может менять Git-дерево.

## Интерфейсы

| Слой | Статус | Комментарий |
|---|---|---|
| core | yes | `devctl.py` |
| api | child_json | JSON-режим для GUI |
| abi | patch_zip_manifest | patch.zip + manifest |
| cli | yes | argparse CLI |
| gui | yes | Tkinter GUI |
| apk | no | не требуется |
| web_localhost | no | не требуется |

## Зависимости

- Python: `>=3.11`, stdlib для CLI.
- GUI: Tkinter, обычно входит в Python-дистрибутив, но на Linux может ставиться отдельно.
- external: Git; PyInstaller нужен только для сборки GUI exe.

## Проверка

```bash
python scripts/smoke_test.py
```

Smoke-тест проверяет `python devctl.py --version`, наличие GUI runner и базовой документации. Полный end-to-end требует отдельного тестового workspace.

## Как изменить под себя

- CLI/core: `devctl.py`.
- GUI: `gui/`.
- Patch prompt: `docs/agent/devctl-patch-prompt-template.md`.
- Сборка EXE: `build/pyinstaller.spec`, `build_exe.ps1`.

## Граница применимости

`devctl` не проверяет смысл патча сам по себе. Он обеспечивает дисциплину применения, preflight, checks, archive и rollback, но качество payload остаётся ответственностью автора патча и reviewer-а.
