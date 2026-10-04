# Внешний контракт zapret_strategy_extractor

Версия контракта: 1

Контракт — это то, на что может опираться другая программа или будущий автор: способ вызова, аргументы, коды возврата и формат трёх выходных файлов. Версия записана в `tool.ini` (`[data] contract_version`), в `src/main.rs` (`CONTRACT_VERSION`) и в каждом `stats.json` (`"contract_version": 1`).

Правило: несовместимое изменение = новая версия контракта + запись в `CHANGELOG.md`. Добавление нового необязательного аргумента, нового поля в JSON или нового комментария в preset несовместимым изменением не считается.

Сгенерированный preset — best-effort кандидат, а не готовая конфигурация: перед применением его проверяют вручную.

## Вызов

```text
cargo run -- <orchestra.log> [--preset-out ФАЙЛ] [--stats-out ФАЙЛ] [--events-out ФАЙЛ]
                             [--base-preset ФАЙЛ] [--min-locks N] [--include-success-only]
                             [--max-blocks N] [--tcp-filter СПИСОК] [--udp-filter СПИСОК]
                             [--no-hostlist-domains] [--progress-lines N]
```

Лаунчеры `run.sh` и `run.bat` передают аргументы как есть и не меняют текущую папку.

| Аргумент | По умолчанию | Смысл |
|---|---|---|
| `<orchestra.log>` | — | Исходный лог. Обязателен. |
| `--preset-out` | `locked_strategies_preset.txt` | Куда записать preset. |
| `--stats-out` | `strategy_stats.json` | Куда записать статистику. |
| `--events-out` | `strategy_events.tsv` | Куда записать список событий. |
| `--base-preset` | нет | Файл, содержимое которого копируется в начало preset вместо встроенного заголовка. |
| `--min-locks` | `1` | Минимум событий LOCK/LOCKED, чтобы стратегия попала в preset. |
| `--include-success-only` | выключен | Брать и стратегии без LOCK, если у них есть SUCCESS. |
| `--max-blocks` | `100` | Предел числа блоков `--new`. |
| `--tcp-filter` | `80,443` | Значение для `--filter-tcp=`. |
| `--udp-filter` | `443` | Значение для `--filter-udp=`. |
| `--no-hostlist-domains` | выключен | Не писать строки `--hostlist-domains=`. |
| `--progress-lines` | `1000000` | Прогресс в stderr каждые N строк; `0` — без прогресса. |

Пути по умолчанию относительные: файлы создаются в текущей папке. Существующие выходные файлы заменяются. Входной лог и `--base-preset` только читаются.

## Вход

Текстовый лог в UTF-8, читается построчно. Распознаются строки следующих видов (остальные пропускаются):

| Строка | Что из неё берётся |
|---|---|
| `profile N (…) lua ФУНКЦИЯ(ключ="значение",… range_in=A range_out=B payload_type=C)` — вся строка, оканчивается `)` | шаг профиля N: функция, параметры, диапазоны, тип нагрузки |
| `desync profile N (…) matches`, `using cached desync profile N (…)` | текущий профиль для следующих событий |
| `circular_quality: current strategy N`, `circular_quality: start from strategy N` | текущая стратегия |
| `hostname: ИМЯ` | текущая цель |
| `host record key 'autostate.ПРОТОКОЛ ЦЕЛЬ'` | текущие протокол и цель |
| `LUA: slm_quality: LOCK [ПРОТОКОЛ] ЦЕЛЬ -> strat=N (…)` | событие `lock` |
| `LUA: slm_quality: [ПРОТОКОЛ] ЦЕЛЬ strat=N SUCCESS a/b` либо `… FAIL a/b` | событие `success` или `fail` |
| `LUA: circular_quality: LOCKED on strategy N…` | событие `lock` |
| `LUA: circular_quality: LOCKED strat N SUCCESS…` | событие `locked_success` |
| `LUA: circular_quality: LOCKED strat N FAIL #a/b for ЦЕЛЬ` | событие `fail` |
| `LUA: circular_quality: FAILURE overrides previous SUCCESS for strat N` | событие `failure_override` |
| строка с `AUTO-UNLOCK` или `auto-unlock` | событие `auto_unlock` (стратегия из `strat=N`/`strategy N` в строке, иначе текущая) |

## Выход

### stats.json

```json
{
  "contract_version": 1,
  "source_log": "путь к логу, как он был передан",
  "total_lines": 36,
  "profile_lua_steps": 5,
  "strategies": [
    {
      "strategy": 1,
      "locks": 4, "locked_successes": 1, "plain_successes": 3,
      "fails": 1, "failure_overrides": 0, "auto_unlocks": 0,
      "first_line": 11, "last_line": 31,
      "protocols": {"quic": 3, "tls": 6},
      "targets": {"www.example.org": 4},
      "profiles": {"3": 6, "5": 3},
      "score": 440
    }
  ],
  "events": [
    {"line": 11, "event": "lock", "strategy": 1, "protocol": "tls", "target": "www.example.org", "profile_id": 3, "details": "rtt=110ms tries=3"}
  ],
  "generated_blocks": 5,
  "notes": ["пометки best-effort, на английском"]
}
```

- `score` = `locks*100 + locked_successes*50 + plain_successes*5 − fails*25 − failure_overrides*80 − auto_unlocks*100`.
- `strategies` отсортированы по убыванию `score`, затем `locks`, `locked_successes`, `plain_successes`, затем по возрастанию номера.
- `protocol`, `target`, `profile_id` могут быть `null`, если лог не дал контекста.
- Файл содержит цели (домены, адреса) из лога: это приватные данные.

### events.tsv

Первая строка — заголовок `line`, `event`, `strategy`, `protocol`, `target`, `profile_id`, `details`; дальше по строке на событие в порядке лога, поля разделены табуляцией, отсутствующее значение — пустое поле.

### preset

1. Содержимое `--base-preset` и пустая строка либо встроенный заголовок.
2. Блок комментариев `# Generated locked/successful strategy blocks` с путём к логу и предупреждением best-effort.
3. Для каждой отобранной стратегии, в порядке `strategies`, по блоку на каждый подходящий шаг профиля: строка `--new`, комментарии (`# Strategy …`, `# Protocols`, `# Targets`, `# Profile`, `# Source profile line`, `# Targets seen`), затем `--filter-tcp=` либо `--filter-udp=`, до трёх `--hostlist-domains=`, `--out-range=`, `--payload=` и `--lua-desync=ФУНКЦИЯ:ключ=значение:…`.
4. Если для стратегии не нашлось шага профиля с параметром `strategy="N"`, блок состоит из `--new` и комментариев.

Шаг профиля подходит стратегии, если у него есть параметр `strategy` с её номером; шаги функций `circular_quality` и `slm_quality` не используются. Параметр `strategy` и пустые параметры в `--lua-desync` не переносятся.

Готовые примеры всех трёх файлов — в `examples/output_expected`.

## stdout и stderr

- stdout: сводка — `Готово.`, `Обработано строк`, `Найдено событий`, `Создано блоков preset`, `Ошибок`, пути к трём файлам и напоминание о ручной проверке.
- stderr: строки прогресса и сообщения об ошибках.

## Коды возврата

| Код | Значение |
|---|---|
| `0` | Лог обработан, три файла записаны. |
| `1` | Ошибка: лог не открылся или содержит байты не в UTF-8, не прочитался `--base-preset`, не создался выходной файл. |
| `2` | Неверные аргументы командной строки. |

## Что не входит в контракт

- Точный текст сводки, прогресса и комментариев в preset.
- Содержимое встроенного заголовка preset.
- Заголовки `Usage:` и `Options:` в `--help`: их печатает библиотека разбора аргументов, они остаются английскими.
- Скорость и расход памяти. События и шаги профилей хранятся в памяти: расход растёт с их числом, а не с размером лога.
