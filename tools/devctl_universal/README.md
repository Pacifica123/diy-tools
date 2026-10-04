# devctl universal

Статус: `tested`  
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

Smoke-тест создаёт во временной папке настоящий workspace с Git-репозиторием и прогоняет через `devctl.py` из капсулы: `plan` без изменений, успешный `start --no-push` (коммит с трейлерами, pre/post-снимки, копия `UserTestSpace`, журнал), повторный `start`, упавшую проверку с автоматическим откатом и удалением патча, отказ на пути с `../`, `reset` и `status --json`. В капсулу ничего не пишется, push не выполняется, сеть не нужна. Без `git` сквозной сценарий пропускается, и тест прямо об этом пишет.

Чего проверка не покрывает: Tkinter GUI, push в remote, `sync`, `self install`, сборку exe, Windows и `run.bat`.

## Контракт

`docs/CONTRACT.md`, версия контракта 1 (совпадает с `formatVersion` манифеста патча): формат патча, коды возврата, что остаётся после запуска.

## История

`CHANGELOG.md` — история капсулы на полке.

## Версия на полке

Здесь лежит devctl 0.6.7 вместе с GUI 0.2.2. Сам devctl развивается в отдельном репозитории и там новее (на момент оформления M3 — 0.8.0 с командами `workspace`, `inbox` и `zip`). Полку и её патчи можно применять любой из этих версий: формат патча один и тот же. Обновлять ли копию на полке — отдельное решение: GUI импортирует `devctl.py` напрямую, и связку нужно проверять запуском окна.

## Как изменить под себя

- CLI/core: `devctl.py`.
- GUI: `gui/`.
- Patch prompt: `docs/agent/devctl-patch-prompt-template.md`.
- Сборка EXE: `build/pyinstaller.spec`, `build_exe.ps1`.

## Граница применимости

`devctl` не проверяет смысл патча сам по себе. Он обеспечивает дисциплину применения, preflight, checks, archive и rollback, но качество payload остаётся ответственностью автора патча и reviewer-а.
