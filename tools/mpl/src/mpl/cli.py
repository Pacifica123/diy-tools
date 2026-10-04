from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mpl.abi import CONTRACT_VERSION, error_result, run_contract_json, stamp
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
    _use_utf8_pipes()

    try:
        if args.abi_json:
            print(run_contract_json(sys.stdin.read()))
            return OK
        source = _read_source(args)
        result = process_text(source, render=not args.no_svg, strict=args.strict)
        written: list[tuple[str, str]] = []
        if args.ast:
            ast = {"contract_version": CONTRACT_VERSION, **result["diagram"]}
            Path(args.ast).write_text(json.dumps(ast, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(("Отчёт", args.ast))
        if args.svg and "svg" in result:
            Path(args.svg).write_text(result["svg"], encoding="utf-8")
            written.insert(0, ("Результат", args.svg))
        json_to_stdout = args.json or not (args.ast or args.svg)
        if json_to_stdout:
            print(json.dumps(stamp(result), ensure_ascii=False, indent=2))
        if args.ast or args.svg:
            # stdout остаётся чистым JSON, если он туда выводится.
            _print_summary(result, written, sys.stderr if json_to_stdout else sys.stdout)
        if args.fail_on_warning and result.get("warnings"):
            return PROCESSING_ERROR
        return OK
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _fail(args, BAD_INPUT, "bad_input", "ошибка входа", exc)
    except Exception as exc:  # noqa: BLE001 - CLI boundary must not leak traceback by default.
        return _fail(args, PROCESSING_ERROR, "processing_error", "ошибка обработки", exc)


def _fail(args: argparse.Namespace, code: int, kind: str, title: str, exc: Exception) -> int:
    if args.abi_json:
        print(json.dumps(error_result(code, kind, str(exc)), ensure_ascii=False, indent=2))
    print(f"mpl: {title}: {exc}", file=sys.stderr)
    return code


def _print_summary(result: dict, written: list[tuple[str, str]], stream) -> None:
    diagram = result["diagram"]
    warnings = result.get("warnings") or []
    lines = [
        "Готово.",
        f"Обработано: 1 диаграмма (узлов: {len(diagram['nodes'])}, рёбер: {len(diagram['edges'])}, групп: {len(diagram['groups'])})",
        f"Создано: {len(written)}",
        f"Предупреждений: {len(warnings)}",
    ]
    lines.extend(f"  - {item}" for item in warnings)
    lines.append("Ошибок: 0")
    lines.extend(f"{title}: {path}" for title, path in written)
    lines.append("Раскладка best-effort: проверь картинку глазами перед использованием.")
    print("\n".join(lines), file=stream)


def _use_utf8_pipes() -> None:
    # JSON-контракт обещает UTF-8 в stdin/stdout независимо от локали и ОС.
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


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
