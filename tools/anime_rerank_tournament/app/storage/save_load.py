from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.domain.models import TournamentState
from app.utils.errors import SaveFileError

# External contract of the save/autosave file, see docs/CONTRACT.md.
CONTRACT_VERSION = 1
SAVE_KIND = "anime_rerank_tournament.save"


def state_to_payload(state: TournamentState) -> dict[str, Any]:
    return {"contract_version": CONTRACT_VERSION, "kind": SAVE_KIND, **state.to_dict(include_undo=True)}


def save_state(path: str | Path, state: TournamentState) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state_to_payload(state), ensure_ascii=False, indent=2)
    # Write next to the target and replace it in one step: a crash in the middle of
    # writing must not leave a half-written autosave instead of the previous good one.
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, target)


def _derived_lists(data: dict[str, Any]) -> tuple[list[int], list[int]]:
    """Round winners and eliminated ids as they follow from the match history."""
    round_number = data.get("round_number", 0)
    completed = data.get("completed_matches", [])
    winners = [m["winner_id"] for m in completed if m.get("round_number") == round_number]
    eliminated = [m["loser_id"] for m in completed if not m.get("is_bye")]
    return winners, eliminated


def _repair_legacy(data: dict[str, Any]) -> None:
    """Saves of 0.1.0 (no contract_version) may carry lists spoiled by the old undo bug.

    The match history in such files is correct, so both lists are rebuilt from it.
    """
    for snapshot in [data, *data.get("undo_stack", [])]:
        snapshot["round_winner_ids"], snapshot["eliminated_ids"] = _derived_lists(snapshot)


def _check_state(state: TournamentState, data: dict[str, Any]) -> None:
    if not state.items:
        raise ValueError("в файле нет ни одного тайтла")
    ids = [item.id for item in state.items]
    known = set(ids)
    if len(known) != len(ids):
        raise ValueError("повторяются id тайтлов")
    if state.mode not in ("light", "hard"):
        raise ValueError(f"неизвестный режим оценивания: {state.mode!r}")
    if state.status not in ("not_started", "in_progress", "finished"):
        raise ValueError(f"неизвестный статус турнира: {state.status!r}")
    matches = state.current_matches + state.completed_matches
    used = set(state.active_ids) | set(state.eliminated_ids) | set(state.round_winner_ids)
    for match in matches:
        used.update(x for x in (match.left_id, match.right_id, match.winner_id, match.loser_id) if x is not None)
    if not used <= known:
        raise ValueError(f"ссылки на несуществующие тайтлы: {sorted(used - known)}")
    winners, eliminated = _derived_lists(data)
    if state.round_winner_ids != winners or state.eliminated_ids != eliminated:
        raise ValueError("списки победителей раунда и выбывших не совпадают с историей матчей")
    playing_ids = [x for m in state.current_matches for x in (m.left_id, m.right_id) if x is not None]
    if len(set(state.active_ids)) != len(state.active_ids) or len(set(playing_ids)) != len(playing_ids):
        raise ValueError("один и тот же тайтл участвует в раунде дважды")
    earlier_losers = {
        m.loser_id for m in state.completed_matches if not m.is_bye and m.round_number < state.round_number
    }
    if earlier_losers & set(playing_ids):
        raise ValueError("в текущем раунде участвуют уже выбывшие тайтлы")
    open_matches = [m for m in state.current_matches if not m.is_bye and not m.is_resolved]
    if state.status == "in_progress" and not open_matches:
        raise ValueError("турнир не завершён, но в нём нет ни одного открытого матча")
    if state.status == "finished" and len(state.active_ids) != 1:
        raise ValueError("турнир завершён, но победитель не определён")


def state_from_payload(data: Any, source: str = "файл сохранения") -> TournamentState:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise SaveFileError(f"Это не сохранение турнира: {source}. Ожидается JSON-объект со списком items.")
    kind = data.get("kind")
    if kind is not None and kind != SAVE_KIND:
        raise SaveFileError(f"Это не сохранение турнира: {source}. В файле указан другой тип данных: {kind!r}.")
    version = data.get("contract_version")
    if version is None:
        legacy = True
    elif isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SaveFileError(f"Сохранение повреждено: {source}. Непонятная версия формата: {version!r}.")
    elif version > CONTRACT_VERSION:
        raise SaveFileError(
            f"Сохранение создано более новой версией программы: {source}. "
            f"Версия формата в файле — {version}, эта программа понимает версии до {CONTRACT_VERSION}. "
            "Обновите программу; файл не изменён."
        )
    else:
        legacy = False
    try:
        if legacy:
            _repair_legacy(data)
        state = TournamentState.from_dict(data)
        for snapshot in state.undo_stack:
            if not isinstance(snapshot, dict):
                raise ValueError("запись в undo_stack не является объектом")
            TournamentState.from_dict(snapshot)
        _check_state(state, data)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        reason = f"нет поля {exc}" if isinstance(exc, KeyError) else str(exc)
        raise SaveFileError(f"Сохранение повреждено: {source}. Причина: {reason}.") from exc
    return state


def load_state(path: str | Path) -> TournamentState:
    source = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise SaveFileError(f"Файл сохранения не найден: {source}") from exc
    except UnicodeDecodeError as exc:
        raise SaveFileError(f"Сохранение повреждено: {source}. Файл не в кодировке UTF-8.") from exc
    except OSError as exc:
        raise SaveFileError(f"Не удалось прочитать файл сохранения: {source}. Причина: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SaveFileError(f"Сохранение повреждено: {source}. Это не корректный JSON ({exc}).") from exc
    return state_from_payload(data, source)
