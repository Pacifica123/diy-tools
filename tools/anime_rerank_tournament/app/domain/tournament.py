from __future__ import annotations

import math
import random
from copy import deepcopy
from datetime import datetime
from typing import Iterable
from uuid import uuid4

from app.domain.models import Match, ScoreMode, TitleItem, TournamentState, now_iso
from app.utils.errors import TournamentError


class TournamentEngine:
    """Stateful single-elimination tournament engine."""

    def __init__(self, state: TournamentState):
        self.state = state

    @classmethod
    def new(cls, items: list[TitleItem], mode: ScoreMode = "light", random_seed: int | None = None) -> "TournamentEngine":
        if not items:
            raise TournamentError("Нельзя начать турнир без тайтлов.")
        seed = int(random_seed if random_seed is not None else random.randint(1, 999_999_999))
        clean_items = [deepcopy(item) for item in items]
        for idx, item in enumerate(clean_items, start=1):
            item.id = idx
            item.wins = 0
            item.losses = 0
            item.bye_count = 0
            item.eliminated_round = None
            item.lost_to_id = None
            item.new_score = None
        state = TournamentState(
            items=clean_items,
            active_ids=[item.id for item in clean_items],
            random_seed=seed,
            mode=mode,
            status="in_progress",
        )
        engine = cls(state)
        engine._create_next_round()
        return engine

    @classmethod
    def from_state(cls, state: TournamentState) -> "TournamentEngine":
        return cls(state)

    def _touch(self) -> None:
        self.state.updated_at = now_iso()

    def _snapshot(self) -> dict:
        return self.state.to_dict(include_undo=False)

    def _push_undo(self) -> None:
        self.state.undo_stack.append(self._snapshot())
        # Prevent autosave from becoming huge on very long tournaments.
        self.state.undo_stack = self.state.undo_stack[-100:]

    def get_item(self, item_id: int) -> TitleItem:
        return self.state.item_by_id(item_id)

    def current_match(self) -> Match | None:
        if self.state.status != "in_progress":
            return None
        for match in self.state.current_matches:
            if not match.is_resolved and not match.is_bye:
                return match
        return None

    def current_match_position(self) -> tuple[int, int]:
        actual = [m for m in self.state.current_matches if not m.is_bye]
        done = len([m for m in actual if m.is_resolved])
        total = len(actual)
        return min(done + 1, total), total

    def estimated_total_rounds(self) -> int:
        n = len(self.state.items)
        if n <= 1:
            return 1
        return math.ceil(math.log2(n))

    def round_plan_lines(self) -> list[str]:
        n = len(self.state.items)
        lines: list[str] = []
        round_no = 1
        while n > 1:
            next_n = math.ceil(n / 2)
            label = "Финал" if n == 2 else f"Раунд {round_no}"
            lines.append(f"{label}: {n} → {next_n}")
            n = next_n
            round_no += 1
        return lines

    def _previous_round_bye_ids(self) -> set[int]:
        previous_round = self.state.round_number - 1
        return {
            match.winner_id
            for match in self.state.completed_matches
            if match.is_bye and match.round_number == previous_round and match.winner_id is not None
        }

    def _choose_bye_id(self, ids: list[int], rng: random.Random) -> int:
        previous_byes = self._previous_round_bye_ids()
        candidates = [item_id for item_id in ids if item_id not in previous_byes]
        if not candidates:
            candidates = ids[:]
        min_bye = min(self.get_item(item_id).bye_count for item_id in candidates)
        candidates = [item_id for item_id in candidates if self.get_item(item_id).bye_count == min_bye]
        return rng.choice(candidates)

    def _make_match(self, round_number: int, left_id: int, right_id: int | None, is_bye: bool = False) -> Match:
        return Match(
            id=str(uuid4()),
            round_number=round_number,
            left_id=left_id,
            right_id=right_id,
            is_bye=is_bye,
        )

    def _create_next_round(self) -> None:
        if len(self.state.active_ids) <= 1:
            self._finish()
            return

        self.state.round_number += 1
        self.state.current_matches = []
        self.state.round_winner_ids = []

        rng = random.Random(self.state.random_seed + self.state.round_number * 10_003)
        participants = self.state.active_ids[:]
        rng.shuffle(participants)

        if len(participants) % 2 == 1:
            bye_id = self._choose_bye_id(participants, rng)
            participants.remove(bye_id)
            item = self.get_item(bye_id)
            item.bye_count += 1
            bye_match = self._make_match(self.state.round_number, bye_id, None, True)
            bye_match.winner_id = bye_id
            bye_match.resolved_at = now_iso()
            self.state.round_winner_ids.append(bye_id)
            self.state.current_matches.append(bye_match)
            self.state.completed_matches.append(deepcopy(bye_match))

        for idx in range(0, len(participants), 2):
            self.state.current_matches.append(
                self._make_match(self.state.round_number, participants[idx], participants[idx + 1], False)
            )

        self._touch()

    def select_winner(self, winner_id: int) -> None:
        match = self.current_match()
        if match is None:
            raise TournamentError("Нет активного матча.")
        if winner_id not in {match.left_id, match.right_id}:
            raise TournamentError("Выбранный победитель не участвует в текущем матче.")
        assert match.right_id is not None
        loser_id = match.right_id if winner_id == match.left_id else match.left_id

        self._push_undo()
        match.winner_id = winner_id
        match.loser_id = loser_id
        match.resolved_at = now_iso()

        winner = self.get_item(winner_id)
        loser = self.get_item(loser_id)
        winner.wins += 1
        loser.losses += 1
        loser.eliminated_round = self.state.round_number
        loser.lost_to_id = winner_id

        self.state.round_winner_ids.append(winner_id)
        self.state.eliminated_ids.append(loser_id)
        self.state.completed_matches.append(deepcopy(match))
        self._touch()
        self._advance_if_round_complete()

    def select_left(self) -> None:
        match = self.current_match()
        if match:
            self.select_winner(match.left_id)

    def select_right(self) -> None:
        match = self.current_match()
        if match and match.right_id is not None:
            self.select_winner(match.right_id)

    def skip_current_match(self) -> None:
        match = self.current_match()
        if match is None:
            return
        self.state.current_matches.remove(match)
        self.state.current_matches.append(match)
        self._touch()

    def _advance_if_round_complete(self) -> None:
        if any(not m.is_resolved and not m.is_bye for m in self.state.current_matches):
            return
        self.state.active_ids = self.state.round_winner_ids[:]
        if len(self.state.active_ids) <= 1:
            self._finish()
        else:
            self._create_next_round()

    def _finish(self) -> None:
        self.state.status = "finished"
        if self.state.active_ids:
            champion = self.get_item(self.state.active_ids[0])
            champion.eliminated_round = None
            champion.lost_to_id = None
        self._touch()

    def undo_last_action(self) -> bool:
        if not self.state.undo_stack:
            return False
        previous = self.state.undo_stack.pop()
        remaining_stack = self.state.undo_stack[:]
        restored = TournamentState.from_dict(previous)
        restored.undo_stack = remaining_stack
        self.state = restored
        self._touch()
        return True

    def is_finished(self) -> bool:
        return self.state.status == "finished"

    def completed_user_match_count(self) -> int:
        return len([m for m in self.state.completed_matches if not m.is_bye])

    def total_required_user_matches(self) -> int:
        return max(0, len(self.state.items) - 1)
