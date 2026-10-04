from __future__ import annotations

import csv
import json
from pathlib import Path

from app.domain.models import CONTRACT_VERSION, SpinRecord


def export_history_txt(records: list[SpinRecord], path: str | Path) -> None:
    lines = []
    for idx, record in enumerate(records, start=1):
        pct = record.probability * 100
        lines.append(f"{idx}. {record.label} | mode={record.mode} | weight={record.effective_weight:g} | p={pct:.2f}% | {record.created_at}")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def export_history_csv(records: list[SpinRecord], path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["index", "label", "mode", "effective_weight", "total_weight", "probability", "created_at"])
        for idx, record in enumerate(records, start=1):
            writer.writerow([idx, record.label, record.mode, record.effective_weight, record.total_weight, record.probability, record.created_at])


def export_history_json(records: list[SpinRecord], path: str | Path) -> None:
    payload = {
        "contract_version": CONTRACT_VERSION,
        "records": [record.to_dict() for record in records],
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def export_summary(records: list[SpinRecord], path: str | Path) -> str:
    """Итог экспорта для показа пользователю (STANDARD §13)."""
    return f"Готово.\nЭкспортировано записей: {len(records)}\nРезультат: {path}"
