# TOOLS.md — реестр DIY-инструментов

| ID | Название | Категория | Зрелость | Флаги | Интерфейсы | Среды | Сеть | Опасность | Где лежит | Проверка |
|---|---|---|---|---|---|---|---|---|---|---|
| devctl_universal | Devctl universal | tooling | M3 | D,O,P,G | cli/gui/patch_zip_manifest | Win expected / Linux expected | possible Git push | yes | tools/devctl_universal | python scripts/smoke_test.py |
| mpl | Mermaid Processor Lite | diagrams | M2 | G | gui/cli/api/json_contract | Win expected / Linux expected | no | no | tools/mpl | python scripts/smoke_test.py |
| random_wheel_app | Колесо рандома | decision | M2 | I | gui/simple_files | Win expected / Linux expected | no | no | tools/random_wheel_app | python scripts/smoke_test.py |
| anime_rerank_tournament | Турнир переоценки аниме | ranking | M2 | I | gui/simple_files | Win expected / Linux expected | no | no | tools/anime_rerank_tournament | python scripts/smoke_test.py |
| logheaderparser | Потоковый парсер шаблонов логов | logs | M2 | S,P | cli/json_report | Win expected / Linux expected | no | no | tools/logheaderparser | python scripts/smoke_test.py |
| zapret_strategy_extractor | Извлекатель zapret-стратегий | logs | M2 | S,G,P | cli/generated_files | Win expected / Linux expected | no | no | tools/zapret_strategy_extractor | python scripts/smoke_test.py |
| video_converter | Конвертер MKV в MP4 | media | M2 | D,P | cli/json_report | Win expected / Linux expected | no | yes | tools/video_converter | python scripts/smoke_test.py |
| react_app_launcher | StartDeck — лаунчер профилей запуска | desktop | M2 | O,P | gui/user_config_json | Win expected / Linux unknown | possible user URLs | no | tools/react_app_launcher | node scripts/smoke_test.js |

## Легенда зрелости

- `M0` — одноразовый эксперимент.
- `M1` — личный инструмент.
- `M2` — переносимая капсула.
- `M3` — стабильная утилита.
- `M4` — infrastructure/platform candidate.

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
