from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

# Версия внешнего контракта (CLI + JSON-отчёт), см. docs/CONTRACT.md.
CONTRACT_VERSION = 1


@dataclass
class FileResult:
    source: str
    output: str
    status: str
    message: str = ""
    deleted_original: bool = False


@dataclass
class Summary:
    found: int = 0
    planned: int = 0
    created: int = 0
    skipped: int = 0
    deleted: int = 0
    errors: int = 0
    dry_run: bool = False


def iter_mkv_files(directory: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.mkv" if recursive else "*.mkv"
    return sorted(p for p in directory.glob(pattern) if p.is_file())


def output_path_for(source: Path, input_dir: Path, output_dir: Path | None) -> Path:
    if output_dir is None:
        return source.with_suffix(".mp4")
    rel = source.relative_to(input_dir)
    return (output_dir / rel).with_suffix(".mp4")


def build_ffmpeg_command(ffmpeg: str, source: Path, output: Path, overwrite: bool) -> list[str]:
    return [
        ffmpeg,
        "-y" if overwrite else "-n",
        "-i",
        str(source),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        str(output),
    ]


def partial_path_for(output: Path) -> Path:
    # ffmpeg пишет во временный файл рядом с результатом; расширение .mp4 нужно ffmpeg для выбора формата.
    return output.with_name(output.stem + ".vc-partial.mp4")


def convert_one(ffmpeg: str, source: Path, output: Path, *, overwrite: bool, dry_run: bool, delete_originals: bool) -> FileResult:
    if output.exists() and not overwrite:
        return FileResult(str(source), str(output), "skipped", "выходной файл уже существует; для перезаписи укажите --overwrite")

    if dry_run:
        return FileResult(str(source), str(output), "planned", "dry-run")

    # Конвертация идёт во временный файл и только после успеха заменяет результат:
    # при ошибке ffmpeg не остаётся битого .mp4, а существующий .mp4 не портится даже с --overwrite.
    partial = partial_path_for(output)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        cmd = build_ffmpeg_command(ffmpeg, source, partial, True)
        completed = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            lines = (completed.stderr or completed.stdout or "").strip().splitlines()
            detail = lines[-1].strip() if lines else "подробностей нет"
            return FileResult(str(source), str(output), "error", f"ffmpeg завершился с кодом {completed.returncode}: {detail}")
        if not partial.is_file() or partial.stat().st_size == 0:
            return FileResult(str(source), str(output), "error", "ffmpeg завершился без ошибки, но выходной файл не создан или пуст")
        os.replace(partial, output)
    except OSError as exc:
        return FileResult(str(source), str(output), "error", f"{type(exc).__name__}: {exc}")
    finally:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass

    deleted = False
    message = "ok"
    if delete_originals:
        try:
            source.unlink()
            deleted = True
        except OSError as exc:
            message = f"mp4 создан, но оригинал не удалён: {type(exc).__name__}: {exc}"

    return FileResult(str(source), str(output), "created", message, deleted_original=deleted)


def write_report(path: Path, summary: Summary, results: list[FileResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract_version": CONTRACT_VERSION,
        "summary": asdict(summary),
        "results": [asdict(r) for r in results],
    }
    # errors="replace": имя файла в не-UTF-8 кодировке не должно ронять запись отчёта после уже сделанной работы.
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", errors="replace")


def print_summary(summary: Summary, report: Path | None, result_location: str) -> None:
    print("Готово.")
    print(f"Найдено: {summary.found}")
    if summary.dry_run:
        print(f"Запланировано: {summary.planned}")
    print(f"Создано: {summary.created}")
    print(f"Пропущено: {summary.skipped}")
    print(f"Удалено оригиналов: {summary.deleted}")
    print(f"Ошибок: {summary.errors}")
    print(f"Dry-run: {'да' if summary.dry_run else 'нет'}")
    print(f"Результат: {result_location}")
    if report:
        print(f"Отчёт: {report}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video-converter",
        description="Пакетная конвертация .mkv в .mp4 через ffmpeg. По умолчанию оригиналы не удаляются.",
    )
    parser.add_argument("directory", type=Path, help="Папка с .mkv файлами")
    parser.add_argument("--recursive", action="store_true", help="Искать .mkv во вложенных папках")
    parser.add_argument("--output-dir", type=Path, help="Папка для .mp4. Если не указана, mp4 создаются рядом с mkv")
    parser.add_argument("--overwrite", action="store_true", help="Перезаписывать существующие .mp4")
    parser.add_argument("--delete-originals", action="store_true", help="Удалить .mkv только после успешной конвертации")
    parser.add_argument("--dry-run", action="store_true", help="Показать план без запуска ffmpeg и без изменений файлов")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="Команда или путь к ffmpeg")
    parser.add_argument("--report", type=Path, help="JSON-отчёт")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        print(f"Ошибка: папка не найдена: {directory}", file=sys.stderr)
        return 2

    ffmpeg_path = shutil.which(args.ffmpeg) or args.ffmpeg
    if not args.dry_run and shutil.which(args.ffmpeg) is None and not Path(args.ffmpeg).is_file():
        print("Ошибка: ffmpeg не найден. Установите ffmpeg или передайте --ffmpeg путь.", file=sys.stderr)
        return 2

    files = iter_mkv_files(directory, args.recursive)
    summary = Summary(found=len(files), dry_run=args.dry_run)
    results: list[FileResult] = []

    if not files:
        print("Нет файлов .mkv для конвертации в указанной папке.")

    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else None
    report_path = args.report.expanduser().resolve() if args.report else None
    if args.delete_originals and not args.dry_run and report_path is None:
        print(
            "Внимание: --delete-originals без --report: список удалённых оригиналов останется только в выводе ниже.",
            file=sys.stderr,
        )

    for source in files:
        output = output_path_for(source, directory, output_dir)
        result = convert_one(
            ffmpeg_path,
            source,
            output,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            delete_originals=args.delete_originals,
        )
        results.append(result)
        if result.status == "created":
            summary.created += 1
        elif result.status == "planned":
            summary.planned += 1
        elif result.status == "skipped":
            summary.skipped += 1
        elif result.status == "error":
            summary.errors += 1
        if result.deleted_original:
            summary.deleted += 1
        print(f"{result.status}: {source} -> {output}{(' | ' + result.message) if result.message else ''}")

    if report_path:
        write_report(report_path, summary, results)
    if args.dry_run:
        result_location = "файлы не создавались (dry-run)"
    elif output_dir is not None:
        result_location = str(output_dir)
    else:
        result_location = f"рядом с исходными файлами в {directory}"
    print_summary(summary, report_path, result_location)
    return 1 if summary.errors else 0


if __name__ == "__main__":
    # Консоль с неподходящей кодировкой не должна обрывать пакет посреди работы из-за имени файла.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")
    raise SystemExit(main())
