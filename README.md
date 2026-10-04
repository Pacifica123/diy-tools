# DIY tools — полка маленьких инструментов

Личная полка небольших инструментов для бытовых, рабочих и исследовательских микропроблем. Каждый инструмент — самодостаточная капсула в `tools/`, которую можно скопировать отдельно, понять, запустить и проверить.

- Реестр инструментов: [TOOLS.md](TOOLS.md) — версии, статусы, флаги риска, что проверено.
- Как устроена капсула: [tools/README.md](tools/README.md).
- Стандарт, по которому ведётся полка: [docs/diy-tool-standard/](docs/diy-tool-standard/README.md), версия `0.2-devctl`.

## Проверка

```bash
python scripts/check_tools_shelf.py            # паспорта, реестр, требования M3 и smoke-тесты всех капсул
python scripts/check_tools_shelf.py --static   # то же без запуска smoke-тестов
```

Нужен Python 3.11 или новее. Отдельным smoke-тестам нужны `git`, `node`, `cargo`, `ffmpeg`: без них соответствующая часть пропускается, и это видно в итоге проверки. GUI-библиотеки (PySide6, Electron) для проверки не нужны — окна автоматически не проверяются.

## Изменения

Изменения приходят devctl-патчами: `devctl plan`, затем `devctl start`. Правила — в [docs/diy-tool-standard/DEVCTL_PATCH_PROTOCOL.md](docs/diy-tool-standard/DEVCTL_PATCH_PROTOCOL.md).
