from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mpl.abi import run_contract_json
from mpl.abi.exit_codes import BAD_INPUT, OK, PROCESSING_ERROR
from mpl.api import process_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mpl",
        description="Mermaid Processor Lite: лёгкий процессор Mermaid-subset в JSON/SVG.",
    )
    parser.add_argument("--input", "-i", help="Путь к .mmd/.mermaid файлу UTF-8.")
    parser.add_argument("--text", help="Mermaid-текст прямо в аргументе.")
    parser.add_argument("--stdin", action="store_true", help="Читать Mermaid-текст из stdin.")
    parser.add_argument("--abi-json", action="store_true", help="Читать ABI JSON из stdin и вернуть ABI JSON в stdout.")
    parser.add_argument("--ast", help="Куда сохранить AST JSON.")
    parser.add_argument("--svg", help="Куда сохранить SVG.")
    parser.add_argument("--json", action="store_true", help="Вывести полный JSON-результат в stdout.")
    parser.add_argument("--no-svg", action="store_true", help="Не строить SVG в результате.")
    parser.add_argument("--strict", action="store_true", help="Падать на первой неподдержанной строке.")
    parser.add_argument("--fail-on-warning", action="store_true", help="Вернуть код ошибки, если есть предупреждения.")
    args = parser.parse_args(argv)

    try:
        if args.abi_json:
            print(run_contract_json(sys.stdin.read()))
            return OK
        source = _read_source(args)
        result = process_text(source, render=not args.no_svg, strict=args.strict)
        if args.ast:
            Path(args.ast).write_text(json.dumps(result["diagram"], ensure_ascii=False, indent=2), encoding="utf-8")
        if args.svg and "svg" in result:
            Path(args.svg).write_text(result["svg"], encoding="utf-8")
        if args.json or not (args.ast or args.svg):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.fail_on_warning and result.get("warnings"):
            return PROCESSING_ERROR
        return OK
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"mpl: ошибка входа: {exc}", file=sys.stderr)
        return BAD_INPUT
    except Exception as exc:  # noqa: BLE001 - CLI boundary must not leak traceback by default.
        print(f"mpl: ошибка обработки: {exc}", file=sys.stderr)
        return PROCESSING_ERROR


def _read_source(args: argparse.Namespace) -> str:
    sources = [bool(args.input), bool(args.text), bool(args.stdin)]
    if sum(sources) != 1:
        raise ValueError("укажи ровно один источник: --input, --text или --stdin")
    if args.input:
        return Path(args.input).read_text(encoding="utf-8")
    if args.text:
        return str(args.text)
    return sys.stdin.read()


if __name__ == "__main__":
    raise SystemExit(main())
