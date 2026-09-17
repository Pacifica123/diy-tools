from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cli import build_chunks, main, parse_blocks, parse_size  # noqa: E402


SAMPLE = """Вступление до первого заголовка.

# Документ

Обычный абзац с **жирным** и [ссылкой](https://example.com).

## Код

```python
# это не Markdown-заголовок
print("hello")
```

## Таблица

| A | B |
|---|---|
| 1 | 2 |
| 3 | 4 |

## Список

- Первый пункт
  продолжение первого пункта
- Второй пункт
  - вложенный пункт
- Третий пункт

## Финал

Последний абзац.
"""


def first_nonblank(text: str) -> str:
    return next(line for line in text.splitlines() if line.strip())


def run() -> int:
    assert parse_size("1M") == 1024 * 1024
    assert parse_size("1.5K") == 1536

    blocks = parse_blocks(SAMPLE)
    fence = next(block for block in blocks if block.kind == "fence")
    assert "# это не Markdown-заголовок" in fence.text
    table = next(block for block in blocks if block.kind == "table")
    assert "| 3 | 4 |" in table.text

    with tempfile.TemporaryDirectory(prefix="markdown_splitter_smoke_") as tmp:
        base = Path(tmp)
        source = base / "Большой документ.md"
        source.write_text(SAMPLE, encoding="utf-8")

        chunks, warnings = build_chunks(source, 170)
        assert len(chunks) >= 3
        assert all(first_nonblank(chunk.text).lstrip().startswith("#") for chunk in chunks), [first_nonblank(c.text) for c in chunks]
        assert sum("```python" in chunk.text for chunk in chunks) == 1, "fenced code block must stay intact"
        assert sum("|---|---|" in chunk.text for chunk in chunks) == 1, "table must stay intact"
        assert any(chunk.context_heading_added for chunk in chunks), "continuation chunks should receive a heading"
        assert any(chunk.oversized for chunk in chunks) or warnings == [], "soft-limit warnings must match oversized chunks"

        out = base / "out"
        code = main([str(source), "--max-size", "170", "--output-dir", str(out), "--json"])
        assert code == 0
        report = json.loads((out / "index.json").read_text(encoding="utf-8"))
        assert report["parts"]
        assert all((out / item["file"]).is_file() for item in report["parts"])
        assert all(first_nonblank((out / item["file"]).read_text(encoding="utf-8")).lstrip().startswith("#") for item in report["parts"])

        # Existing non-empty directories are never overwritten.
        assert main([str(source), "--output-dir", str(out)]) == 1

        front = base / "frontmatter.md"
        front.write_text("---\ntitle: Demo\n---\n\nТекст до секции.\n\n## Раздел\nТело.\n", encoding="utf-8")
        front_chunks, _ = build_chunks(front, 120)
        assert front_chunks[0].text.startswith("---\ntitle: Demo\n---\n"), "front matter must stay first"
        assert "# Раздел" in front_chunks[0].text or "# frontmatter" in front_chunks[0].text

        broken = base / "broken.md"
        broken.write_text("# X\n\n```python\nprint(1)\n", encoding="utf-8")
        assert main([str(broken), "--output-dir", str(base / "broken_out")]) == 1

    print("markdown_splitter smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
