# tools — общая полка DIY-инструментов

Эта папка вводит первую общую полку инструментов по `DIY Tool Standard v0.1-devctl`.

Каждая подпапка — капсула инструмента:

- `README.md` — человеческий контракт;
- `tool.ini` — паспорт инструмента;
- `run.bat` / `run.sh` — запуск, если применимо;
- `examples/` и `scripts/smoke_test.*` — минимальная проверка, если применимо.

Общий реестр: `../TOOLS.md`.

Правило полки: сюда не кладутся `.git/`, `.devctl/`, `node_modules/`, `target/`, `dist/`, `build`-артефакты, Python bytecode, приватные generated reports и локальные абсолютные пути.
