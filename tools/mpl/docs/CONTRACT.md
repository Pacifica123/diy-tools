# Контракт mpl

Версия контракта: 1

Внешний контракт `mpl` (вызов CLI, аргументы, коды возврата, формат входа, JSON-результат, AST- и SVG-файлы, stdout/stderr, что в контракт не входит) описан в одном месте — [`ABI.md`](ABI.md). Здесь только указатель, чтобы описание не дублировалось.

| Вопрос | Где ответ |
|---|---|
| Как вызывать и какие аргументы | [ABI.md — Вызов](ABI.md#вызов) |
| Формат входа (stdin JSON, файл) | [ABI.md — Вход](ABI.md#вход), subset Mermaid — [README.md — Вход](../README.md#вход) |
| JSON-результат, AST- и SVG-файлы, JSON ошибки | [ABI.md — Выход](ABI.md#выход) |
| stdout/stderr | [ABI.md — stdout и stderr](ABI.md#stdout-и-stderr) |
| Коды возврата | [ABI.md — Exit codes CLI](ABI.md#exit-codes-cli) |
| Что НЕ входит в контракт | [ABI.md — Граница контракта](ABI.md#граница-контракта) |

Версия контракта `1` соответствует ABI `mpl-json 0.1`. Она записана в `tool.ini` (`[data] contract_version`), в коде (`src/mpl/abi/json_contract.py`: `CONTRACT_VERSION`, `ABI_VERSION`) и в каждом JSON, который выдаёт инструмент (`"contract_version": 1`).

Правило: несовместимое изменение = новая версия контракта + запись в [`CHANGELOG.md`](../CHANGELOG.md).
