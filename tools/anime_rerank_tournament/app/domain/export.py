from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from app.domain.ranking import RankedItem
from app.domain.models import Match


def ranked_to_rows(ranking: list[RankedItem]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ranked in ranking:
        item = ranked.item
        old = item.old_score
        new = item.new_score
        delta = None if old is None or new is None else new - float(old)
        rows.append(
            {
                "rank": ranked.rank,
                "source_index": item.source_index,
                "title": item.title,
                "old_score": old,
                "new_score": new,
                "delta": delta,
                "episodes": item.episodes,
                "type": item.type,
                "comment": item.comment,
                "wins": item.wins,
                "losses": item.losses,
                "bye_count": item.bye_count,
                "eliminated_round": item.eliminated_round,
                "lost_to": ranked.lost_to_title,
            }
        )
    return rows


def export_ranking_csv(path: str | Path, ranking: list[RankedItem]) -> None:
    rows = ranked_to_rows(ranking)
    fieldnames = list(rows[0].keys()) if rows else []
    with Path(path).open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def export_ranking_json(path: str | Path, ranking: list[RankedItem]) -> None:
    Path(path).write_text(json.dumps(ranked_to_rows(ranking), ensure_ascii=False, indent=2), encoding="utf-8")


def export_ranking_txt(path: str | Path, ranking: list[RankedItem]) -> None:
    lines = ["Итоговый рейтинг", "=" * 80, ""]
    for ranked in ranking:
        item = ranked.item
        delta = ""
        if item.old_score is not None and item.new_score is not None:
            diff = item.new_score - float(item.old_score)
            delta = f" ({diff:+g})"
        lines.append(
            f"{ranked.rank:>4}. {item.title} | старая: {item.old_score} | новая: {item.new_score}{delta} | "
            f"{item.episodes} | {item.type}"
        )
        if ranked.lost_to_title:
            lines.append(f"      выбыл в раунде {item.eliminated_round}, проиграл: {ranked.lost_to_title}")
        if item.comment:
            lines.append(f"      комментарий: {item.comment}")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def export_matches_json(path: str | Path, matches: list[Match]) -> None:
    Path(path).write_text(
        json.dumps([match.to_dict() for match in matches], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
