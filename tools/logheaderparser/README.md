# logheaderparser

Статус: `draft`  
Зрелость: `M2`  
Флаги: `S, P`  
Основной интерфейс: `cli`

## Что делает

Rust CLI для потокового поиска шаблонов в больших логах. Инструмент читает файл построчно, нормализует переменные токены и группирует похожие строки в шаблоны.

## Когда использовать

Когда есть большой неизвестный лог и нужно быстро понять повторяющиеся типы строк без загрузки всего файла в память.

## Быстрый запуск

Linux:

```bash
sh run.sh examples/sample.log --json report.json --progress-lines 0
```

Windows:

```powershell
run.bat examples\sample.log --json report.json --progress-lines 0
```

Напрямую:

```bash
cargo run -- examples/sample.log --json report.json --top 10 --progress-lines 0
```

## Вход

Один текстовый лог-файл. Для больших файлов используйте `--progress-lines`, `--max-patterns`, `--examples` и `--threshold`.

## Выход

- stdout summary: количество строк, байт, шаблонов и top-N шаблонов;
- JSON-report через `--json`, если указан путь.

JSON-report может содержать путь к исходному файлу и примеры строк лога. Поэтому инструмент помечен флагом `P`.

## Побочные эффекты и предупреждения

- Удаляет файлы: нет.
- Перезаписывает файлы: да, если `--json` указывает на существующий файл.
- Использует сеть: нет.
- Запускает внешние команды: нет.
- Может содержать приватные данные: да, report может включать path и examples.

## Интерфейсы

| Слой | Статус | Комментарий |
|---|---|---|
| core | embedded | логика внутри `src/main.rs` |
| api | no | пока не выделен library crate |
| abi | json_report | stdout + JSON report |
| cli | yes | clap CLI |
| gui | no | не требуется |
| apk | no | не требуется |
| web_localhost | no | не требуется |

## Зависимости

- Rust: stable toolchain, edition 2021.
- Cargo crates: `anyhow`, `clap`, `regex`, `serde`, `serde_json` с bounded major versions.
- external: `none`.

## Проверка

```bash
python scripts/smoke_test.py
```

Если `cargo` доступен, smoke-тест выполнит `cargo run` на `examples/sample.log`. Если `cargo` недоступен, тест сделает source-level проверку и честно напечатает, что сборка пропущена.

## Как изменить под себя

- Токенизация и нормализация: `normalize_token` в `src/main.rs`.
- Алгоритм похожести: `similarity`.
- Лимиты памяти/примеров: CLI-аргументы `--max-patterns`, `--examples`.

## Граница применимости

Алгоритм эвристический: он помогает увидеть повторяющиеся шаблоны, но не гарантирует идеальную кластеризацию всех лог-строк. Примеры строк в отчёте нужно отключать через `--examples 0`, если нельзя сохранять содержимое лога.
