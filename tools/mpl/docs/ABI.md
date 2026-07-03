# ABI mpl-json 0.1

ABI нужен, чтобы `mpl` можно было вызывать не только из GUI, но и из другого инструмента через JSON.

## Вход

Минимальный stdin JSON:

```json
{
  "source": "flowchart TD\nA[Старт] --> B[Финиш]",
  "render": true
}
```

Вместо `source` можно передать:

```json
{
  "input_path": "examples/input/basic_flow.mmd",
  "render": true
}
```

## Выход

```json
{
  "ok": true,
  "diagram": {
    "kind": "flowchart",
    "direction": "TD",
    "nodes": [],
    "edges": [],
    "groups": [],
    "warnings": []
  },
  "warnings": [],
  "svg": "<svg ...",
  "abi": {
    "name": "mpl-json",
    "version": "0.1"
  }
}
```

Если `render=false`, поле `svg` не возвращается.

## Exit codes CLI

| Код | Значение |
|---:|---|
| 0 | Успешная обработка |
| 2 | Ошибка входа, JSON или файла |
| 3 | Ошибка обработки |
| 5 | Нет GUI-зависимости PySide6/PyQt6 при запуске GUI |

## Граница контракта

`mpl-json 0.1` стабилизирует структуру `nodes`, `edges`, `groups`, `warnings`, но не обещает пиксельную неизменность SVG-раскладки.
