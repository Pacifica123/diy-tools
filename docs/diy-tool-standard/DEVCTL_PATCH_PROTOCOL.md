# Devctl Patch Protocol для DIY Tool Standard

Версия: `0.2-devctl`.

Этот документ фиксирует, как будущие инструменты и изменения стандарта должны оформляться для применения через `devctl`.

## 1. Роль devctl

`devctl` — не менеджер инструментов и не build-система. В этой методологии он выполняет роль конвейера изменений:

```text
идея/исправление → patch.zip → plan → start → checks → commit → archive → UserTestSpace
```

Он нужен, чтобы инструменты не появлялись в workspace как хаотичные ручные правки.

## 2. Структура патча

```text
patch_YYYYMMDD_HHMMSS_slug.zip
  manifest.json
  files/
    docs/...
    tools/tool_id/...
  PATCH_SUMMARY.md
  reports/
    source-analysis.md       # опционально
    test-notes.md            # опционально
```

Всё, что должно попасть в проект, кладётся в `files/`.

## 3. Минимальный manifest

```json
{
  "formatVersion": 1,
  "patchId": "2026-06-12-example-tool",
  "title": "Добавить example_tool",
  "summary": "Добавляет капсулу инструмента example_tool по DIY Tool Standard.",
  "kind": "tooling",
  "createdAt": "2026-06-12T10:30:00Z",
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
      "name": "Проверить наличие паспорта и README инструмента",
      "cwd": ".",
      "command": "python -c \"from pathlib import Path; missing=[p for p in ['tools/example_tool/README.md','tools/example_tool/tool.ini'] if not Path(p).is_file()]; raise SystemExit('missing: '+str(missing) if missing else 0)\"",
      "requiredCommands": ["python"],
      "timeoutSeconds": 120
    }
  ],
  "commit": {
    "message": "docs/tools: добавить example_tool"
  },
  "push": {
    "remote": "origin",
    "branch": "main"
  },
  "archive": {
    "nameSlug": "example-tool",
    "exclude": [
      ".git/",
      "node_modules/",
      "target/",
      "dist/",
      "build/",
      "coverage/",
      "__pycache__/",
      ".env",
      ".env.*",
      "*.sqlite",
      "*.db"
    ]
  }
}
```

## 4. Проверки по типу патча

### Docs-only patch

Проверить наличие файлов, JSON-валидность manifest/registry, отсутствие пустых основных документов.

### Python tool

Минимум:

```text
python -m py_compile ...
python scripts/smoke_test.py
```

Если py_compile создаёт bytecode, devctl должен очистить его, но patch payload не должен содержать `__pycache__`.

### Rust tool

Минимум:

```text
cargo check
cargo test      # если тесты есть
```

Не включать `target/`.

### Node/Electron tool

Минимум:

```text
npm install     # обычно не в devctl-check, если окружение не гарантировано
npm run build   # если проект уже node-based и зависимости доступны
```

В patch payload не включать `node_modules/`, `dist/`, `build/`, если это не отдельный release payload.

### Generated-output tool

Проверка должна создавать результат на synthetic/sample input и убеждаться, что audit output существует.

### Destructive tool

Проверка только на копии данных или synthetic sandbox. Не применять к реальным пользовательским путям.

### Проверка всей полки

Патч, который трогает `tools/`, `TOOLS.md` или стандарт, запускает одну общую проверку:

```text
python scripts/check_tools_shelf.py
```

Она сверяет реестр с паспортами, требует для M3 файлы из §4.1 стандарта, запускает smoke-тесты всех капсул и проверяет, что они не оставили следов. Время проверки определяют две Rust-капсулы: каждая собирается во временный каталог, поэтому `timeoutSeconds` у такой проверки — не меньше 1800.

### Что нужно помнить о проверках devctl

- Каталог `cwd` проверки должен существовать **до** применения патча: предполётная проверка идёт раньше наложения файлов. Проверку для нового каталога запускают из существующего (обычно `.`).
- Проверка не должна оставлять следов в проекте: всё, что она создала, попадёт в коммит или остановит его.
- `archive.nameSlug` задаётся всегда: без него каталог запуска получает имя `…_patch_…`.
- Патч описывает файлы целиком; удаления перечисляются в `apply.delete`. Удалить путь с компонентом `target`, `node_modules`, `.git`, `.devctl` патч не может — такое убирают вручную.
- Имена файлов с пробелами и кириллицей в патче допустимы; примеры полки их содержат намеренно.

## 5. Что запрещено в patch payload

Запрещено добавлять:

- `.git/`;
- `.devctl/`;
- `.env`, `.env.*`;
- приватные логи, дампы, медиа и таблицы;
- `node_modules/`;
- `target/`;
- Python bytecode/cache;
- локальные absolute-path configs;
- собранные exe/apk без отдельного release-обоснования.

Если нужен release payload, он должен быть явно описан в `PATCH_SUMMARY.md`, а archive policy должна отличать source patch от release artifact.

## 6. `PATCH_SUMMARY.md`

Каждый патч должен кратко отвечать:

```text
Что добавлено?
Почему это нужно?
Какие файлы изменены?
Какие проверки есть?
Какие риски остались?
Как откатить или чем заменить?
```

Для инструмента добавить:

```text
Класс инструмента:
Зрелость:
Флаги риска:
Основной интерфейс:
Поддерживаемые среды:
Источник/якорь задачи:
```

## 7. Связь с реестром

Если патч добавляет или повышает инструмент до M1+, он должен обновить `TOOLS.md` или локальный registry-файл проекта. Если реестр ещё не создан, патч должен добавить его из шаблона.

M0-эксперименты можно хранить вне общего реестра, но нельзя оставлять destructive M0 без явного предупреждения в коде.

## 8. Критерий хорошего devctl-патча

Хороший патч можно проверить до применения, применить одной командой, получить зелёные проверки и понять из summary, почему изменение существует.

Плохой патч требует ручных догадок, тащит мусор, скрывает generated/cache файлы, меняет много несвязанных вещей или не объясняет связь с микропроблемой.

## 9. История workspace одним архивом

Начиная с devctl 0.8.0 команда `devctl zip`, запущенная в workspace, собирает его историю — коммиты, патчи, запуски, копии и заметки — в один небольшой архив для чтения нейросетью. Такой архив удобно прикладывать к задаче на следующий патч вместо пересказа истории. Секреты из содержимого команда не вычищает.
