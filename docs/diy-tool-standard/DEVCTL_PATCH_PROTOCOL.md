# Devctl Patch Protocol для DIY Tool Standard

Версия: `0.1-devctl`.

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
