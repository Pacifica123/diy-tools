# Source Tool Audit: что добавлено в стандарт после разбора примеров

Этот документ фиксирует не полный аудит качества, а извлечённые методологические требования.

## 1. `random_wheel_app`

Наблюдение: инструмент уже отделяет domain logic от UI, имеет parser, storage, autosave, export, smoke test и документацию формата входа.

Что стандарт забирает:

- класс `I` / interactive-subjective;
- autosave как обязательное требование для долгих ручных сессий;
- `random seed` как часть воспроизводимости случайного выбора;
- экспорт истории как способ проверить и повторно использовать результат;
- GUI не должен сам принимать доменное решение, а должен вызывать engine.

## 2. `anime_rerank_tournament`

Наблюдение: инструмент имеет турнирную механику, scoring modes, undo, autosave, export и отдельные документы по input/scoring/architecture.

Что стандарт забирает:

- preference/ranking tools требуют объяснимых scoring rules;
- undo/history не роскошь, если пользователь делает много субъективных выборов;
- итоговая оценка должна быть audit-able: история матчей и JSON/CSV/TXT export;
- domain engine, ranking, scoring и UI должны быть разделены.

## 3. `logheaderparser`

Наблюдение: Rust CLI потоково обрабатывает огромный лог, ограничивает количество шаблонов и примеров, пишет JSON-отчёт, печатает progress. Одновременно видны риски: wildcard-зависимости в Cargo.toml и report с абсолютным личным путём/примерами строк.

Что стандарт забирает:

- класс `S` / streaming-large-data;
- bounded memory/limits обязательны для больших логов;
- progress не декоративен, а часть UX долгих задач;
- JSON report — нормальный ABI для анализа;
- отчёты по приватным логам могут раскрывать paths/examples и требуют флага `P`;
- wildcard-зависимости не соответствуют M3 без обоснования.

## 4. `zapret_strategy_extractor`

Наблюдение: доменно-специфический Rust CLI извлекает стратегии из больших логов, генерирует preset, stats JSON и event TSV. В коде прямо указано, что генерация best-effort и часть данных не восстанавливается полностью.

Что стандарт забирает:

- класс `G` / generated-output;
- generated preset/config — гипотеза, а не гарантированно правильный результат;
- нужен audit output рядом с итоговым generated file;
- notes о невосстановимых данных — обязательная часть честного контракта;
- base preset/header лучше передавать как вход, а не реконструировать магически.

## 5. `react-app-launcher-v2.2-blank-window-fix`

Наблюдение: Electron-инструмент запускает приложения, папки, файлы, сайты и команды; хранит пользовательский config вне source tree; имеет build-specific fix для Vite `base: './'`.

Что стандарт забирает:

- класс `O` / orchestrator для инструментов, запускающих внешние команды;
- запуск `command` опаснее запуска `app/folder/file/url` и требует отдельной маркировки;
- source config и user config — разные сущности;
- packaged mode нужно проверять отдельно от dev mode;
- build notes должны фиксировать известные ловушки упаковки.

## 6. `video_converter.py`

Наблюдение: полезный M0/M1-кандидат, но с жёстко прошитым личным путём и удалением оригинального `.mkv` после конвертации.

Что стандарт забирает:

- hardcoded absolute personal paths запрещены для M1+;
- удаление оригиналов после конвертации = `D`/destructive;
- destructive media tool должен иметь `--delete-originals`, dry-run/backup/report или output-only режим;
- MoviePy/ffmpeg-зависимость должна быть явно описана;
- ошибка в одном файле не должна скрывать неполный итог всей пачки.

## 7. `devctl_project`

Наблюдение: devctl задаёт дисциплину patch-based разработки: manifest, files root, checks, pre/post/failed archives, UserTestSpace, Git-policy, игнорирование generated/cache мусора.

Что стандарт забирает:

- все будущие изменения стандарта и инструментов должны приходить патчами;
- patch summary и checks являются частью методологии, а не украшением;
- build/cache/generated directories не должны попадать в source patch;
- UserTestSpace подходит для ручной проверки GUI, Electron, Rust/Node сборок и других грязных операций.

## 8. Итоговое изменение относительно исходного мета-документа

Мета-документ уже задавал DIY, универсальность, русификацию, капсулы, `tool.ini`, уровни зрелости и анти-бюрократию. После разбора примеров стандарт добавляет классы поведения:

```text
D destructive
P private-data
N network
O orchestrator
S streaming-large-data
G generated-output
I interactive-subjective
A android-apk
W web-localhost
```

Эти флаги важнее попытки заранее придумать единую архитектуру для всех инструментов. Они позволяют каждому инструменту получить ровно те дополнительные требования, которые нужны из-за его реального поведения.
