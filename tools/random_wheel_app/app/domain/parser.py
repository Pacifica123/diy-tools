from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path

from app.domain.models import WheelItem


@dataclass
class ParseIssue:
    line_number: int
    text: str
    message: str


@dataclass
class ParseResult:
    items: list[WheelItem]
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.items)

    def stats(self) -> dict[str, int]:
        with_value = sum(1 for item in self.items if item.value is not None)
        return {
            "Всего": len(self.items),
            "Со значением": with_value,
            "Без значения": len(self.items) - with_value,
            "Проблемы": len(self.issues),
        }


def read_text_file(path: str | Path) -> str:
    p = Path(path)
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return p.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return p.read_text(encoding="utf-8", errors="replace")


def _to_float(raw: str) -> float | None:
    text = raw.strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_numeric_value(raw: str) -> float | None:
    parsed = _to_float(raw)
    if parsed is None or not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def parse_wheel_file(path: str | Path) -> ParseResult:
    return parse_wheel_text(read_text_file(path))


def parse_wheel_text(text: str) -> ParseResult:
    items: list[WheelItem] = []
    issues: list[ParseIssue] = []
    next_id = 1

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue

        label = line
        value = None

        if ":" in line:
            maybe_label, maybe_value = line.rsplit(":", 1)
            value = parse_numeric_value(maybe_value)
            # Если после ':' вообще не число (например, «Игра: подзаголовок»), двоеточие —
            # часть названия: вариантом становится вся строка, текст не обрезается.
            if value is not None or not maybe_value.strip() or _to_float(maybe_value) is not None:
                label = maybe_label.strip()
            if value is None:
                issues.append(ParseIssue(line_number, raw_line, "После ':' должно быть положительное число. Строка добавлена как вариант без значения."))

        label = label.strip()
        if not label:
            issues.append(ParseIssue(line_number, raw_line, "Пустое имя варианта."))
            continue

        items.append(WheelItem(id=next_id, label=label, value=value, source_line=line_number))
        next_id += 1

    return ParseResult(items=items, issues=issues)
