# TOOLS.md — реестр DIY-инструментов

Стандарт: `docs/diy-tool-standard/STANDARD.md`, версия `0.2-devctl`. Все капсулы полки имеют зрелость M3.

Колонки «Версия», «Статус», «Зрелость», «Флаги», «Опасность» и «Проверка» повторяют `tool.ini` капсулы; расхождение ловит `python scripts/check_tools_shelf.py`.

| ID | Название | Версия | Статус | Категория | Зрелость | Флаги | Интерфейсы | Среды | Сеть | Опасность | Где лежит | Проверка |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| devctl_universal | Devctl universal | 0.6.7-cli-0.2.2-gui | tested | tooling | M3 | D,O,P,G | cli/gui/patch_zip_manifest | Win expected / Linux tested | possible Git push | yes | tools/devctl_universal | python scripts/smoke_test.py |
| mpl | Mermaid Processor Lite | 0.2.0 | tested | diagrams | M3 | G | gui/cli/api/json_contract | Win expected / Linux tested | no | no | tools/mpl | python scripts/smoke_test.py |
| markdown_splitter | Нарезчик Markdown | 0.3.0 | tested | text | M3 | P,G | cli/json_report | Win expected / Linux tested | no | no | tools/markdown_splitter | python scripts/smoke_test.py |
| random_wheel_app | Колесо рандома | 0.2.0 | tested | decision | M3 | I | gui/simple_files | Win expected / Linux tested | no | no | tools/random_wheel_app | python scripts/smoke_test.py |
| anime_rerank_tournament | Турнир переоценки аниме | 0.2.0 | tested | ranking | M3 | I | gui/simple_files | Win expected / Linux tested | no | no | tools/anime_rerank_tournament | python scripts/smoke_test.py |
| logheaderparser | Потоковый парсер шаблонов логов | 0.2.0 | working | logs | M3 | S,P | cli/json_report | Win expected / Linux expected | no | no | tools/logheaderparser | python scripts/smoke_test.py |
| zapret_strategy_extractor | Извлекатель zapret-стратегий | 0.2.0 | working | logs | M3 | S,G,P | cli/generated_files | Win expected / Linux expected | no | no | tools/zapret_strategy_extractor | python scripts/smoke_test.py |
| video_converter | Конвертер MKV в MP4 | 0.3.0 | tested | media | M3 | D,P | cli/json_report | Win expected / Linux tested | no | yes | tools/video_converter | python scripts/smoke_test.py |
| react_app_launcher | StartDeck — лаунчер профилей запуска | 0.4.0 | working | desktop | M3 | O,P | gui/user_config_json/dry_run_cli | Win expected / Linux unknown | possible user URLs | no | tools/react_app_launcher | node scripts/smoke_test.js |

## Что проверено, а что нет

«Среды» читаются так: `tested` — smoke-тест капсулы действительно проходит в этой среде; `expected` — должно работать, но не запускалось; `unknown` — неизвестно. Что именно покрывает автоматическая проверка каждой капсулы, написано в её `tool.ini` (`[checks] tested_scope`) и в разделе «Проверка» её README. Коротко:

| ID | Автоматически проверяется | Не проверяется |
|---|---|---|
| devctl_universal | сквозной сценарий `plan`/`start`/откат/`reset` во временном workspace | Tkinter GUI, push, `sync`, сборка exe |
| mpl | разбор и SVG на семи примерах, CLI, JSON-контракт | окно PySide6 |
| markdown_splitter | нарезка пяти примеров, инварианты, dry-run, ошибки входа | большие файлы |
| random_wheel_app | разбор списков, вращения с seed, autosave, экспорт, файлы сохранений | окно PySide6 |
| anime_rerank_tournament | разбор списков, турнир с undo, оба режима оценок, autosave, экспорт | окно PySide6 |
| logheaderparser | JSON-отчёты трёх прогонов против эталонов — только если есть `cargo` | большие логи |
| zapret_strategy_extractor | preset, статистика и события трёх прогонов против эталонов — только если есть `cargo` | настоящий orchestra-лог |
| video_converter | dry-run, отчёт, перезапись и удаление на копии с заглушкой ffmpeg, настоящая конвертация при наличии ffmpeg | большие и реальные файлы |
| react_app_launcher | ядро запуска и формат конфига из чистого Node | окно Electron, реальный запуск программ, сборка |

Windows и `run.bat` не проверялись ни у одной капсулы.

Статус `working` вместо `tested` у трёх капсул поставлен намеренно: у двух Rust-инструментов автор версии не мог выполнить сборку, у StartDeck главный процесс Electron переписан без запуска окна. Причины записаны в их README.

## Легенда зрелости

- `M0` — одноразовый эксперимент.
- `M1` — личный инструмент.
- `M2` — переносимая капсула.
- `M3` — стабильная утилита: smoke-тест с регрессионными эталонами, версионированный контракт, история изменений (стандарт, §4.1).
- `M4` — infrastructure/platform candidate.

## Легенда статусов

- `draft` — черновик.
- `working` — работает у автора; автоматическая проверка неполна или не выполнялась автором версии.
- `tested` — smoke-тест с регрессией проходит в средах, помеченных `tested`.
- `stable` — проверен и давно используется.
- `broken`, `deprecated` — сломан, выведен из употребления.

## Легенда флагов

- `D` destructive.
- `P` private-data.
- `N` network.
- `O` orchestrator.
- `S` streaming-large-data.
- `G` generated-output.
- `I` interactive-subjective.
- `A` android-apk.
- `W` web-localhost.
