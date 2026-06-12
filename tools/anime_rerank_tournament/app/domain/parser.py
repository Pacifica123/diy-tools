from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from app.domain.models import TitleItem


ENTRY_START_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")
DETAIL_RE = re.compile(r"^\s*(\d+(?:[\.,]\d+)?)\s+([0-9?]+(?:/[0-9?]+)?)\s+(.+?)\s*$")
STATS_RE = re.compile(r"(Сериалы|Фильмы|OVA|ONA|Эпизоды|Дни)\s*:", re.IGNORECASE)
HEADER_RE = re.compile(r"^\s*#\s+Название", re.IGNORECASE)


@dataclass
class ParseIssue:
    line_number: int
    text: str
    message: str


@dataclass
class ParseResult:
    items: list[TitleItem]
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.items)

    def stats(self) -> dict[str, int]:
        result: dict[str, int] = {"Всего": len(self.items)}
        for item in self.items:
            key = item.type.strip() or "Без типа"
            result[key] = result.get(key, 0) + 1
        episodes_total = 0
        for item in self.items:
            episodes_total += parse_seen_episodes(item.episodes)
        result["Эпизоды"] = episodes_total
        return result


def parse_seen_episodes(value: str) -> int:
    value = (value or "").strip()
    match = re.match(r"^(\d+)(?:/(\d+|\?))?$", value)
    if not match:
        return 0
    return int(match.group(1))


def read_text_file(path: str | Path) -> str:
    p = Path(path)
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return p.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return p.read_text(encoding="utf-8", errors="replace")


def parse_score(value: str) -> float | None:
    value = value.strip().replace(",", ".")
    try:
        parsed = float(value)
    except ValueError:
        return None
    if parsed.is_integer():
        return int(parsed)
    return parsed


def parse_title_file(path: str | Path) -> ParseResult:
    return parse_title_text(read_text_file(path))


def parse_title_text(text: str) -> ParseResult:
    items: list[TitleItem] = []
    issues: list[ParseIssue] = []
    current_index: int | None = None
    current_title: str | None = None
    comment_lines: list[str] = []
    auto_id = 1

    def flush_without_details(line_number: int) -> None:
        nonlocal current_index, current_title, comment_lines
        if current_index is not None and current_title:
            issues.append(
                ParseIssue(
                    line_number=line_number,
                    text=current_title,
                    message="Запись началась, но не найдена строка с оценкой/эпизодами/типом.",
                )
            )
        current_index = None
        current_title = None
        comment_lines = []

    lines = text.splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        if HEADER_RE.match(line):
            continue
        if STATS_RE.search(line):
            continue

        detail_match = DETAIL_RE.match(raw_line)
        if detail_match and current_index is not None and current_title:
            score_raw, episodes, title_type = detail_match.groups()
            items.append(
                TitleItem(
                    id=auto_id,
                    source_index=current_index,
                    title=current_title.strip(),
                    old_score=parse_score(score_raw),
                    episodes=episodes.strip(),
                    type=title_type.strip(),
                    comment="\n".join(comment_lines).strip() or None,
                )
            )
            auto_id += 1
            current_index = None
            current_title = None
            comment_lines = []
            continue

        start_match = ENTRY_START_RE.match(raw_line)
        if start_match:
            # A new title starts. If the previous one had no details, keep an issue and reset it.
            if current_index is not None:
                flush_without_details(line_number)
            current_index = int(start_match.group(1))
            current_title = start_match.group(2).strip()
            comment_lines = []
            continue

        if current_index is not None:
            comment_lines.append(line)
        else:
            issues.append(ParseIssue(line_number, raw_line, "Строка не относится ни к одной записи."))

    if current_index is not None:
        flush_without_details(len(lines))

    return ParseResult(items=items, issues=issues)
