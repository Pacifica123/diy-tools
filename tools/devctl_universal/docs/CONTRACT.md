# Внешний контракт devctl_universal

Версия контракта: 1

Версия контракта капсулы совпадает с `formatVersion` манифеста патча: это главный внешний формат, на который опираются авторы патчей. Она записана в `tool.ini` (`[data] contract_version`) и в `docs/patch-manifest.example.json` (`"formatVersion": 1`); `devctl.py` отклоняет манифест с другим значением.

Правило: несовместимое изменение формата патча, кодов возврата или раскладки workspace = новая версия контракта + запись в `CHANGELOG.md`.

Этот документ — указатель. Подробности лежат в файлах, на которые он ссылается, и не дублируются.

## Патч

`patch.zip` = `manifest.json` + `files/` + необязательный `PATCH_SUMMARY.md`.

- Поля манифеста и пример: `docs/patch-manifest.example.json`.
- Обязательны `formatVersion: 1`, непустые `patchId`, `title`, `summary`, объект `apply`, `commit.message`.
- Пути — относительные POSIX-пути внутри проекта; `..`, абсолютные пути и `.git` отклоняются.
- Как писать патч вместе с нейросетью: `docs/agent/devctl-patch-prompt-template.md`.

## Вызов и коды возврата

```text
python devctl.py [-w WORKSPACE] <init|sync|status|inspect|plan|start|reset|completion|self> [флаги]
```

| Код | Значение |
|---|---|
| `0` | успех; для `start` также «применять нечего» |
| `1` | `start`: проверка не прошла, commit или push завершился ошибкой |
| `2` | некорректный патч, непройденная предполётная проверка, ошибка workspace или аргументов |
| `130` | `start` прерван с клавиатуры |

Флаг `--json` даёт машинно-читаемый вывод; GUI использует именно его.

## Что остаётся после запуска

- Коммит в проекте с трейлерами `Patch-Id`, `Patch-SHA256`, `Devctl-Version`.
- `archives/<время>_<slug>_<sha7 патча>/`: `report.md`, `logs/`, снимки `pre_*.zip`, `post_*.zip` или `failed_*.zip`.
- `UserTestSpace/project_<время>_after_<slug>_<sha7>/project` — копия успешного состояния.
- Запись в `.devctl/state.json`.

Раскладка workspace и конфигурация: `docs/devctl-universal-v0.3-README.md`, `docs/workspace.example.json`. Установка как команды: `docs/release-cli.md`.

## Что не входит в контракт

- Точный текст сообщений, отчёта `report.md` и логов.
- Внешний вид и поведение GUI.
- Внутренние функции `devctl.py`: GUI импортирует их напрямую, но сторонним программам следует использовать CLI и `--json`.
