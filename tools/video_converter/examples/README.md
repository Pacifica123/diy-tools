# Примеры и регрессионные эталоны

## `input/`

Синтетические входные данные. Файлы `.mkv` и `.mp4` здесь — маленькие текстовые заглушки, а не настоящее видео: для dry-run и для прогона с заглушкой ffmpeg содержимое не важно. Настоящий ffmpeg на них завершится с ошибкой.

| Файл | Зачем |
|---|---|
| `clip one.mkv` | имя с пробелом |
| `тестовое видео.mkv` | кириллица и пробел |
| `already done.mkv` + `already done.mp4` | результат уже существует: без `--overwrite` файл пропускается |
| `вложенная папка/nested clip.mkv` | находится только с `--recursive` |
| `not a video.txt` | не `.mkv`, должен игнорироваться |

Посмотреть план, ничего не меняя (из папки инструмента):

```bash
python src/cli.py ./examples/input --recursive --dry-run
```

## `output_expected/`

Эталоны, полученные реальным запуском инструмента. Для каждого сценария — JSON-отчёт и stdout. Абсолютные пути заменены метками `<INPUT>`, `<OUTPUT>`, `<REPORT>`, разделитель путей приведён к `/`.

| Сценарий | Команда (в smoke-тесте) |
|---|---|
| `dry_run` | `--dry-run` прямо на `input/` |
| `dry_run_recursive` | `--dry-run --recursive --overwrite --delete-originals --output-dir …` на копии |
| `convert` | `--recursive` на копии с заглушкой ffmpeg |
| `delete_overwrite` | `--recursive --overwrite --delete-originals` на той же копии; заглушка ломает `clip one` и не создаёт результат для `nested clip` |
| `output_dir` | `--recursive --output-dir "готовые файлы"` на свежей копии |

Smoke-тест работает во временной папке и в `examples/` ничего не пишет. Обновить эталоны после осознанного изменения контракта:

```bash
python scripts/smoke_test.py --update-expected
```

Настоящие медиафайлы в репозитории не хранятся: если ffmpeg установлен, smoke-тест сам создаёт односекундный ролик во временной папке.
