from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from app.domain.models import CONTRACT_VERSION, WheelSession

# Формат файла описан в docs/CONTRACT.md. Несовместимое изменение формата =
# новая версия контракта + запись в CHANGELOG.md.

VALID_MODES = ("equal", "weighted")


class SessionFormatError(ValueError):
    """Файл сохранения нельзя загрузить. Текст ошибки — для пользователя, по-русски."""


def write_session(session: WheelSession, path: str | Path) -> None:
    target = Path(path)
    text = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
    # Сначала пишем соседний временный файл, затем подменяем: оборванная запись
    # не оставит вместо прежнего сохранения пустой или обрезанный файл.
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, target)


def _reject_constant(name: str) -> Any:
    raise SessionFormatError(f"Файл сохранения повреждён: недопустимое число {name}.")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise SessionFormatError(f"Это не файл сохранения колеса или он повреждён: {detail}.")


def _validate(data: Any) -> None:
    _require(isinstance(data, dict), "в корне JSON ожидался объект")

    version = data.get("contract_version", 0)  # поля нет в файлах версии 0.1.0
    _require(_is_int(version) and version >= 0, "поле contract_version должно быть целым неотрицательным числом")
    if version > CONTRACT_VERSION:
        raise SessionFormatError(
            f"Файл сохранения создан более новой версией инструмента: версия формата {version}, "
            f"эта версия понимает не выше {CONTRACT_VERSION}. Обновите инструмент. Файл не изменён."
        )

    items = data.get("items")
    _require(isinstance(items, list) and bool(items), "нет списка вариантов items")
    ids: set[int] = set()
    for number, raw in enumerate(items, start=1):
        where = f"items[{number}]"
        _require(isinstance(raw, dict), f"{where} должен быть объектом")
        _require(_is_int(raw.get("id")), f"{where}: поле id должно быть целым числом")
        _require(raw["id"] not in ids, f"{where}: повторяется id {raw['id']}")
        ids.add(raw["id"])
        _require(isinstance(raw.get("label"), str) and bool(raw["label"].strip()), f"{where}: пустое или нестроковое поле label")
        _require(raw.get("value") is None or _is_number(raw["value"]), f"{where}: поле value должно быть числом или null")
        _require(_is_int(raw.get("source_line", 0)), f"{where}: поле source_line должно быть целым числом")

    active_ids = data.get("active_ids")
    _require(isinstance(active_ids, list), "нет списка active_ids")
    for value in active_ids:
        _require(_is_int(value) and value in ids, f"active_ids ссылается на неизвестный вариант {value!r}")

    options = data.get("options")
    _require(isinstance(options, dict), "нет объекта options")
    _require(options.get("mode", "equal") in VALID_MODES, f"неизвестный режим options.mode: {options.get('mode')!r}")
    for key in ("spin_duration_ms", "min_turns", "max_turns", "random_seed"):
        _require(key not in options or _is_int(options[key]), f"options.{key} должно быть целым числом")
    _require(isinstance(options.get("remove_winner", False), bool), "options.remove_winner должно быть true или false")

    history = data.get("history")
    _require(isinstance(history, list), "нет списка history")
    for number, raw in enumerate(history, start=1):
        where = f"history[{number}]"
        _require(isinstance(raw, dict), f"{where} должен быть объектом")
        _require(_is_int(raw.get("item_id")), f"{where}: поле item_id должно быть целым числом")
        _require(isinstance(raw.get("label"), str), f"{where}: поле label должно быть строкой")
        _require(raw.get("mode") in VALID_MODES, f"{where}: неизвестный режим {raw.get('mode')!r}")
        for key in ("effective_weight", "total_weight", "probability"):
            _require(_is_number(raw.get(key)), f"{where}: поле {key} должно быть числом")
        _require(isinstance(raw.get("created_at"), str), f"{where}: поле created_at должно быть строкой")

    if "spin_count" in data:
        _require(_is_int(data["spin_count"]) and data["spin_count"] >= 0, "spin_count должно быть целым неотрицательным числом")
    for key in ("created_at", "updated_at"):
        _require(key not in data or isinstance(data[key], str), f"поле {key} должно быть строкой")


def read_session(path: str | Path) -> WheelSession:
    """Читает файл сохранения. При любой проблеме бросает SessionFormatError
    с русским текстом; сам файл не изменяется."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise SessionFormatError(f"Файл сохранения не найден: {source}") from None
    except UnicodeDecodeError:
        raise SessionFormatError("Файл сохранения повреждён: это не текст в кодировке UTF-8.") from None
    except OSError as exc:
        raise SessionFormatError(f"Не удалось открыть файл сохранения {source}: {exc}") from None

    if not text.strip():
        raise SessionFormatError("Файл сохранения повреждён: файл пуст.")
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise SessionFormatError(
            f"Файл сохранения повреждён: это не корректный JSON (строка {exc.lineno}, столбец {exc.colno})."
        ) from None
    except RecursionError:
        raise SessionFormatError("Файл сохранения повреждён: слишком глубокая вложенность JSON.") from None

    _validate(data)
    try:
        return WheelSession.from_dict(data)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise SessionFormatError(f"Это не файл сохранения колеса или он повреждён: {exc!r}.") from None
