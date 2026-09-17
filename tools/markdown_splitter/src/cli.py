from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*(?:\n)?$")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*(?:\n)?$")
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*?)(?:\n)?$")
LIST_ITEM_RE = re.compile(r"^( {0,3})(?:[-+*]|\d+[.)])[ \t]+")
BLOCKQUOTE_RE = re.compile(r"^ {0,3}>")
INDENTED_RE = re.compile(r"^(?: {4}|\t)")
HTML_OPEN_RE = re.compile(r"^ {0,3}<(details|summary|pre|table|div|section|article|aside|blockquote)(?:\s|>|$)", re.IGNORECASE)
HTML_COMMENT_OPEN_RE = re.compile(r"^ {0,3}<!--")


class SplitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Block:
    kind: str
    text: str
    heading_level: int | None = None
    heading_title: str | None = None

    @property
    def size_bytes(self) -> int:
        return len(self.text.encode("utf-8"))


@dataclass
class Chunk:
    text: str
    title: str
    context_heading_added: bool
    size_bytes: int
    oversized: bool


def parse_size(value: str) -> int:
    raw = value.strip().upper().replace("IB", "").replace("B", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KMG]?)", raw)
    if not m:
        raise argparse.ArgumentTypeError("размер должен выглядеть как 500K, 1M, 1.5M или число байт")
    number = float(m.group(1))
    unit = m.group(2)
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[unit]
    result = int(number * mult)
    if result <= 0:
        raise argparse.ArgumentTypeError("размер должен быть больше нуля")
    return result


def ensure_newline(text: str) -> str:
    return text if not text or text.endswith("\n") else text + "\n"


def heading_from_block_text(text: str) -> tuple[int, str] | None:
    lines = text.splitlines()
    if not lines:
        return None
    m = ATX_HEADING_RE.match(lines[0] + "\n")
    if m:
        return len(m.group(1)), m.group(2).strip()
    if len(lines) >= 2 and SETEXT_RE.match(lines[1] + "\n"):
        level = 1 if lines[1].lstrip().startswith("=") else 2
        return level, lines[0].strip()
    return None


def _is_special_start(lines: list[str], i: int) -> bool:
    line = lines[i]
    if not line.strip():
        return True
    if FENCE_OPEN_RE.match(line):
        return True
    if ATX_HEADING_RE.match(line):
        return True
    if BLOCKQUOTE_RE.match(line):
        return True
    if LIST_ITEM_RE.match(line):
        return True
    if INDENTED_RE.match(line):
        return True
    if HTML_COMMENT_OPEN_RE.match(line) or HTML_OPEN_RE.match(line):
        return True
    if i + 1 < len(lines) and SETEXT_RE.match(lines[i + 1]) and line.strip():
        return True
    if i + 1 < len(lines) and _looks_like_table_header(line, lines[i + 1]):
        return True
    return False


def _looks_like_table_separator(line: str) -> bool:
    stripped = line.strip()
    if "|" not in stripped:
        return False
    stripped = stripped.strip("|")
    cells = [cell.strip() for cell in stripped.split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _looks_like_table_header(line: str, next_line: str) -> bool:
    return bool(line.strip()) and "|" in line and _looks_like_table_separator(next_line)


def _consume_fence(lines: list[str], i: int) -> tuple[Block, int]:
    opener = FENCE_OPEN_RE.match(lines[i])
    assert opener is not None
    marker = opener.group(1)
    ch = marker[0]
    min_len = len(marker)
    close_re = re.compile(rf"^ {{0,3}}{re.escape(ch)}{{{min_len},}}[ \t]*(?:\n)?$")
    j = i + 1
    while j < len(lines):
        if close_re.match(lines[j]):
            j += 1
            return Block("fence", "".join(lines[i:j])), j
        j += 1
    raise SplitError(f"незакрытый fenced code block, начиная со строки {i + 1}")


def _consume_html(lines: list[str], i: int) -> tuple[Block, int]:
    line = lines[i]
    if HTML_COMMENT_OPEN_RE.match(line):
        j = i + 1
        if "-->" in line:
            return Block("html", line), j
        while j < len(lines):
            if "-->" in lines[j]:
                j += 1
                return Block("html", "".join(lines[i:j])), j
            j += 1
        raise SplitError(f"незакрытый HTML-комментарий, начиная со строки {i + 1}")

    m = HTML_OPEN_RE.match(line)
    assert m is not None
    tag = m.group(1)
    close_re = re.compile(rf"</{re.escape(tag)}\s*>", re.IGNORECASE)
    j = i + 1
    if close_re.search(line):
        return Block("html", line), j
    while j < len(lines):
        if close_re.search(lines[j]):
            j += 1
            return Block("html", "".join(lines[i:j])), j
        j += 1
    # HTML blocks are often intentionally left implicit in Markdown. If no explicit
    # closing tag exists, fall back to a paragraph-like block until a blank line.
    j = i + 1
    while j < len(lines) and lines[j].strip():
        j += 1
    return Block("html", "".join(lines[i:j])), j


def _consume_list_item(lines: list[str], i: int) -> tuple[Block, int]:
    start = LIST_ITEM_RE.match(lines[i])
    assert start is not None
    base_indent = len(start.group(1))
    j = i + 1
    while j < len(lines):
        line = lines[j]
        if not line.strip():
            k = j + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k >= len(lines):
                j = k
                break
            nxt = lines[k]
            next_item = LIST_ITEM_RE.match(nxt)
            leading = len(nxt) - len(nxt.lstrip(" "))
            if next_item and len(next_item.group(1)) <= base_indent:
                break
            if leading <= base_indent and not BLOCKQUOTE_RE.match(nxt):
                break
            j = k
            continue
        item = LIST_ITEM_RE.match(line)
        if item and len(item.group(1)) <= base_indent:
            break
        leading = len(line) - len(line.lstrip(" "))
        if leading <= base_indent and not BLOCKQUOTE_RE.match(line):
            break
        j += 1
    if j == i + 1:
        return Block("list_item", lines[i]), j
    return Block("list_item", "".join(lines[i:j])), j


def parse_blocks(text: str) -> list[Block]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines(keepends=True)
    if text and (not lines or not lines[-1].endswith("\n")):
        # splitlines(keepends=True) already keeps the final non-newline line.
        pass
    blocks: list[Block] = []
    i = 0

    # YAML front matter is protected as one block only at the beginning.
    if lines and lines[0].strip() == "---":
        j = 1
        while j < len(lines) and lines[j].strip() not in {"---", "..."}:
            j += 1
        if j < len(lines):
            j += 1
            blocks.append(Block("frontmatter", "".join(lines[:j])))
            i = j

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            blocks.append(Block("blank", "".join(lines[i:j])))
            i = j
            continue

        if FENCE_OPEN_RE.match(line):
            block, i = _consume_fence(lines, i)
            blocks.append(block)
            continue

        if HTML_COMMENT_OPEN_RE.match(line) or HTML_OPEN_RE.match(line):
            block, i = _consume_html(lines, i)
            blocks.append(block)
            continue

        m = ATX_HEADING_RE.match(line)
        if m:
            blocks.append(Block("heading", line, len(m.group(1)), m.group(2).strip()))
            i += 1
            continue

        if i + 1 < len(lines) and SETEXT_RE.match(lines[i + 1]) and line.strip():
            level = 1 if lines[i + 1].lstrip().startswith("=") else 2
            blocks.append(Block("heading", line + lines[i + 1], level, line.strip()))
            i += 2
            continue

        if i + 1 < len(lines) and _looks_like_table_header(line, lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].strip() and "|" in lines[j]:
                j += 1
            blocks.append(Block("table", "".join(lines[i:j])))
            i = j
            continue

        if BLOCKQUOTE_RE.match(line):
            j = i + 1
            while j < len(lines) and (BLOCKQUOTE_RE.match(lines[j]) or not lines[j].strip()):
                j += 1
            blocks.append(Block("blockquote", "".join(lines[i:j])))
            i = j
            continue

        if LIST_ITEM_RE.match(line):
            block, i = _consume_list_item(lines, i)
            blocks.append(block)
            continue

        if INDENTED_RE.match(line):
            j = i + 1
            while j < len(lines) and (INDENTED_RE.match(lines[j]) or not lines[j].strip()):
                j += 1
            blocks.append(Block("indented_code", "".join(lines[i:j])))
            i = j
            continue

        j = i + 1
        while j < len(lines) and not _is_special_start(lines, j):
            j += 1
        blocks.append(Block("paragraph", "".join(lines[i:j])))
        i = j

    return blocks


def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = name.strip().lower()
    out: list[str] = []
    pending_sep = False
    for ch in name:
        if ch.isalnum() or ch in {"-", "_"}:
            if pending_sep and out and out[-1] != "_":
                out.append("_")
            pending_sep = False
            out.append(ch)
        elif ch.isspace() or ch in {".", ":", "/", "\\", "|", "?", "*", '"', "<", ">"}:
            pending_sep = True
    result = "".join(out).strip("._-")[:max_len].rstrip("._-")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if not result or result in reserved:
        return "part"
    return result


def _first_heading_title(blocks: list[Block], fallback: str) -> str:
    for block in blocks:
        if block.kind == "heading" and block.heading_title:
            return block.heading_title
    return fallback


def split_blocks(blocks: list[Block], max_bytes: int, source_title: str) -> tuple[list[Chunk], list[str]]:
    if not blocks:
        return [], []

    # YAML front matter is meaningful only at the very beginning of a Markdown
    # document. Keep it before any generated heading in the first chunk.
    first_frontmatter = ""
    if blocks and blocks[0].kind == "frontmatter":
        first_frontmatter = blocks[0].text
        blocks = blocks[1:]

    warnings: list[str] = []
    chunks: list[Chunk] = []
    current: list[str] = []
    current_size = 0
    current_title = source_title
    current_context_added = False
    current_has_payload = False
    heading_stack: dict[int, Block] = {}

    def current_nearest_heading() -> Block | None:
        if not heading_stack:
            return None
        return heading_stack[max(heading_stack)]

    def context_prefix() -> tuple[str, str, bool]:
        nearest = current_nearest_heading()
        if nearest is not None:
            return ensure_newline(nearest.text), nearest.heading_title or source_title, True
        synthetic = f"# {source_title}\n\n"
        return synthetic, source_title, True

    def start_new(prefix: str = "", title: str | None = None, context_added: bool = False) -> None:
        nonlocal current, current_size, current_title, current_context_added, current_has_payload
        current = [prefix] if prefix else []
        current_size = len(prefix.encode("utf-8"))
        current_title = title or source_title
        current_context_added = context_added
        current_has_payload = False

    def flush() -> None:
        nonlocal current, current_size, current_has_payload
        text = "".join(current).lstrip("\n")
        if not text.strip():
            start_new()
            return
        size = len(text.encode("utf-8"))
        chunks.append(Chunk(text=ensure_newline(text), title=current_title, context_heading_added=current_context_added, size_bytes=size, oversized=size > max_bytes))
        if size > max_bytes:
            warnings.append(f"часть {len(chunks)} имеет {size} байт > лимита {max_bytes}: внутри есть неделимый Markdown-блок")
        start_new()

    start_new(first_frontmatter)

    for block in blocks:
        if block.kind == "blank" and not current and not current_has_payload:
            continue

        # A real heading is the best natural boundary. Flush before it if the
        # existing chunk already has payload and adding heading+future text would
        # otherwise make the next chunk harder to read.
        if block.kind == "heading":
            if current_has_payload and current_size + block.size_bytes > max_bytes:
                flush()
            level = block.heading_level or 1
            heading_stack[level] = block
            for deeper in [lvl for lvl in heading_stack if lvl > level]:
                del heading_stack[deeper]
            if not current:
                current_title = block.heading_title or source_title
                current_context_added = False

        candidate_size = current_size + block.size_bytes
        if candidate_size > max_bytes and current_has_payload:
            flush()
            if block.kind != "heading":
                prefix, title, added = context_prefix()
                start_new(prefix, title, added)

        if block.kind != "heading" and not current_has_payload and not heading_stack:
            # For the first chunk, put the generated title *after* YAML front matter.
            # Front matter must remain byte-position zero to retain its semantics.
            synthetic = f"# {source_title}\n\n"
            current.append(synthetic)
            current_size += len(synthetic.encode("utf-8"))
            current_title = source_title
            current_context_added = True
        elif not current and block.kind != "heading":
            prefix, title, added = context_prefix()
            start_new(prefix, title, added)

        # Never create a useless heading-only chunk for one protected block.
        # If prefix/heading + one atomic block itself exceeds the limit, keep the
        # block intact and mark the resulting chunk as oversized.
        current.append(block.text)
        current_size += block.size_bytes
        if block.kind != "blank":
            current_has_payload = True
        if block.kind == "heading" and not current_context_added:
            current_title = block.heading_title or source_title

    flush()
    return chunks, warnings


def choose_output_dir(source: Path, requested: Path | None) -> Path:
    if requested is not None:
        path = requested
        if path.exists() and any(path.iterdir()):
            raise SplitError(f"выходная папка не пуста: {path}")
        return path
    base = source.with_name(f"{source.stem}_parts")
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = source.with_name(f"{source.stem}_parts_{index}")
        if not candidate.exists():
            return candidate
        index += 1


def build_chunks(source: Path, max_bytes: int) -> tuple[list[Chunk], list[str]]:
    try:
        text = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SplitError("файл должен быть UTF-8 Markdown") from exc
    blocks = parse_blocks(text)
    source_title = source.stem.replace("_", " ").strip() or "Markdown"
    return split_blocks(blocks, max_bytes=max_bytes, source_title=source_title)


def write_chunks(source: Path, output_dir: Path, chunks: list[Chunk], warnings: list[str], max_bytes: int) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    width = max(3, len(str(len(chunks))))
    used: set[str] = set()
    entries = []
    for index, chunk in enumerate(chunks, start=1):
        slug = sanitize_filename(chunk.title)
        base = f"{index:0{width}d}_{slug}"
        filename = base + ".md"
        suffix = 2
        while filename.lower() in used:
            filename = f"{base}_{suffix}.md"
            suffix += 1
        used.add(filename.lower())
        path = output_dir / filename
        path.write_text(chunk.text, encoding="utf-8", newline="\n")
        actual_size = path.stat().st_size
        entries.append(
            {
                "index": index,
                "file": filename,
                "title": chunk.title,
                "sizeBytes": actual_size,
                "contextHeadingAdded": chunk.context_heading_added,
                "oversized": actual_size > max_bytes,
            }
        )

    report = {
        "formatVersion": 1,
        "source": source.name,
        "maxBytes": max_bytes,
        "parts": entries,
        "warnings": warnings,
    }
    (output_dir / "index.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Нарезает UTF-8 Markdown на самостоятельные части, не разрывая fenced code blocks, "
            "таблицы, blockquote и отдельные пункты списков. Продолжения получают контекстный заголовок."
        )
    )
    parser.add_argument("source", type=Path, help="исходный .md файл")
    parser.add_argument("--max-size", type=parse_size, default=parse_size("1M"), help="мягкий максимум части: 500K, 1M, 1.5M или байты (по умолчанию 1M)")
    parser.add_argument("--output-dir", type=Path, default=None, help="выходная папка; должна отсутствовать или быть пустой")
    parser.add_argument("--dry-run", action="store_true", help="ничего не записывать, только показать план")
    parser.add_argument("--json", action="store_true", help="печатать итоговый отчёт JSON в stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    source: Path = args.source
    if not source.is_file():
        parser.error(f"файл не найден: {source}")
    if source.suffix.lower() not in {".md", ".markdown", ".mdown", ".mkd"}:
        print(f"Предупреждение: расширение {source.suffix or '(нет)'} не похоже на Markdown.", file=sys.stderr)

    try:
        chunks, warnings = build_chunks(source, args.max_size)
        if not chunks:
            raise SplitError("исходный файл пуст")
        output_dir = choose_output_dir(source, args.output_dir)
        if args.dry_run:
            report = {
                "formatVersion": 1,
                "source": source.name,
                "maxBytes": args.max_size,
                "outputDir": str(output_dir),
                "parts": [
                    {
                        "index": i,
                        "title": chunk.title,
                        "sizeBytes": len(chunk.text.encode("utf-8")),
                        "contextHeadingAdded": chunk.context_heading_added,
                        "oversized": len(chunk.text.encode("utf-8")) > args.max_size,
                    }
                    for i, chunk in enumerate(chunks, start=1)
                ],
                "warnings": warnings,
                "dryRun": True,
            }
        else:
            report = write_chunks(source, output_dir, chunks, warnings, args.max_size)
            report["outputDir"] = str(output_dir)
            report["dryRun"] = False
    except SplitError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        action = "Будет создано" if args.dry_run else "Создано"
        print(f"{action} частей: {len(report['parts'])}")
        print(f"Папка: {report['outputDir']}")
        for part in report["parts"]:
            marker = " [выше лимита]" if part["oversized"] else ""
            filename = part.get("file", f"часть {part['index']}")
            print(f"  {part['index']:03d}: {filename} — {part['sizeBytes']} байт{marker}")
        for warning in warnings:
            print(f"Предупреждение: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
