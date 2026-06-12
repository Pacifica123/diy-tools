from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


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


def convert_one(ffmpeg: str, source: Path, output: Path, *, overwrite: bool, dry_run: bool, delete_originals: bool) -> FileResult:
    if output.exists() and not overwrite:
        return FileResult(str(source), str(output), "skipped", "output already exists; use --overwrite")

    if dry_run:
        return FileResult(str(source), str(output), "planned", "dry-run")

    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_command(ffmpeg, source, output, overwrite)
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "ffmpeg failed").strip().splitlines()[-1:]
        return FileResult(str(source), str(output), "error", message[0] if message else "ffmpeg failed")

    deleted = False
    if delete_originals:
        source.unlink()
        deleted = True

    return FileResult(str(source), str(output), "created", "ok", deleted_original=deleted)


def write_report(path: Path, summary: Summary, results: list[FileResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": asdict(summary),
        "results": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_summary(summary: Summary, report: Path | None) -> None:
    print("Готово.")
    print(f"Найдено: {summary.found}")
    print(f"Создано: {summary.created}")
    print(f"Пропущено: {summary.skipped}")
    print(f"Удалено оригиналов: {summary.deleted}")
    print(f"Ошибок: {summary.errors}")
    print(f"Dry-run: {'да' if summary.dry_run else 'нет'}")
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

    for source in files:
        output = output_path_for(source, directory, args.output_dir.expanduser().resolve() if args.output_dir else None)
        result = convert_one(
            ffmpeg_path,
            source,
            output,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            delete_originals=args.delete_originals,
        )
        results.append(result)
        if result.status in {"created", "planned"}:
            summary.created += 0 if result.status == "planned" else 1
        elif result.status == "skipped":
            summary.skipped += 1
        elif result.status == "error":
            summary.errors += 1
        if result.deleted_original:
            summary.deleted += 1
        print(f"{result.status}: {source} -> {output}{(' | ' + result.message) if result.message else ''}")

    if args.report:
        write_report(args.report.expanduser().resolve(), summary, results)
    print_summary(summary, args.report.expanduser().resolve() if args.report else None)
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
