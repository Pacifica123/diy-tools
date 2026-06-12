# Prompt-шаблон для сборки devctl-патча

Скопируйте этот текст в новую ChatGPT-сессию, когда нужно попросить собрать не полный архив проекта, а корректный `devctl`-патч.

```text
Ты работаешь с devctl workspace и должен вернуть не полный архив проекта, а полноценный devctl-патч.

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

patch_YYYYMMDD_HHMMSS_short_slug.zip
  manifest.json
  PATCH_SUMMARY.md
  files/
    relative/path/in/project.ext

Правила для files/:
- пути внутри files/ должны быть относительными к project/;
- не клади абсолютные пути;
- не клади .git/, .env, секреты, __pycache__/, *.pyc, *.pyo, .pytest_cache/, .venv/, dist/, build/, node_modules/;
- если devctl копирует целые файлы, клади в files/ уже финальные версии изменённых файлов;
- не меняй unrelated-файлы ради косметики.

Минимальный manifest.json:

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
```
