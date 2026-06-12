# zapret_strategy_extractor

Статус: `draft`  
Зрелость: `M2`  
Флаги: `S, G, P`  
Основной интерфейс: `cli`

## Что делает

Rust CLI, который потоково читает `orchestra_*.log` из zapret 2 GUI, извлекает LOCK/SUCCESS-события стратегий и генерирует best-effort preset-кандидат плюс audit-файлы.

## Когда использовать

Когда нужно не вручную выкапывать успешные zapret-стратегии из большого debug-лога, а получить список кандидатов для ручной проверки.

## Быстрый запуск

Linux:

```bash
sh run.sh examples/sample_orchestra.log --preset-out preset.txt --stats-out stats.json --events-out events.tsv --progress-lines 0
```

Windows:

```powershell
run.bat examples\sample_orchestra.log --preset-out preset.txt --stats-out stats.json --events-out events.tsv --progress-lines 0
```

Напрямую:

```bash
cargo run -- examples/sample_orchestra.log --preset-out preset.txt --stats-out stats.json --events-out events.tsv --progress-lines 0
```

## Вход

Оригинальный `orchestra_*.log`, а не агрегированный `report.json`. Опционально можно передать `--base-preset`, чтобы сохранить рабочий header/base preset.

## Выход

- generated preset `.txt`;
- JSON stats/audit report;
- TSV event list для ручной проверки.

Generated preset — гипотеза, а не готовая истина. Перед применением к реальной конфигурации его нужно проверить вручную.

## Побочные эффекты и предупреждения

- Удаляет файлы: нет.
- Перезаписывает файлы: да, если output-файлы уже существуют.
- Использует сеть: нет.
- Запускает внешние команды: нет.
- Может содержать приватные данные: да, stats/events могут содержать targets/domains из лога.

## Интерфейсы

| Слой | Статус | Комментарий |
|---|---|---|
| core | embedded | логика в `src/main.rs` |
| api | no | library crate не выделен |
| abi | generated_files | preset + JSON + TSV |
| cli | yes | clap CLI |
| gui | no | не требуется |
| apk | no | не требуется |
| web_localhost | no | не требуется |

## Зависимости

- Rust: stable toolchain, edition 2021.
- Cargo crates: `anyhow`, `clap`, `regex`, `serde`, `serde_json`.
- external: `none`.

## Проверка

```bash
python scripts/smoke_test.py
```

Если `cargo` доступен, smoke-тест выполнит `cargo run` на sample log и проверит наличие preset/stats/events. Если `cargo` недоступен, будет выполнена source-level проверка.

## Как изменить под себя

- Парсинг log-событий: `parse_*` функции в `src/main.rs`.
- Scoring: `score_strategy`.
- Генерация preset: `write_preset`.

## Граница применимости

Инструмент не восстанавливает всё, что было в исходной GUI-конфигурации. В коде и report это помечено как best-effort. Blob paths, часть base/header и некоторые детали могут быть восстановлены только через `--base-preset` или ручную правку.
