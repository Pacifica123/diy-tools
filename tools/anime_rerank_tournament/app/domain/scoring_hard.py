from __future__ import annotations

import math

from app.domain.ranking import RankedItem
from app.utils.rounding import round_half_up


def hard_scores_for_size(n: int) -> list[int]:
    """Return score for each rank index, best to worst.

    The function intentionally assigns by protected zones and allows missing grades
    on small lists, following the conflict-resolution rules from the specification.
    """
    if n <= 0:
        return []

    scores: list[int | None] = [None] * n
    upper_half_size = math.ceil(n / 2)
    lower_start = upper_half_size

    # Bottom protected zones: 1, then 2, then 3, then the rest of the lower half as 4.
    pointer = n - 1

    def assign_from_bottom(count: int, score: int, stop_index: int = 0) -> None:
        nonlocal pointer
        remaining = max(0, count)
        while remaining > 0 and pointer >= stop_index:
            if scores[pointer] is None:
                scores[pointer] = score
                remaining -= 1
            pointer -= 1

    assign_from_bottom(min(10, n), 1, 0)
    assign_from_bottom(round_half_up(n * 0.01), 2, lower_start)
    assign_from_bottom(round_half_up(n * 0.05), 3, lower_start)

    for idx in range(lower_start, n):
        if scores[idx] is None:
            scores[idx] = 4

    # Upper half: lower half of it gets 5, middle zone gets 6.
    upper_count = upper_half_size
    count_5 = upper_count // 2
    first_five_index = upper_count - count_5
    for idx in range(first_five_index, upper_count):
        if scores[idx] is None:
            scores[idx] = 5
    for idx in range(0, first_five_index):
        if scores[idx] is None:
            scores[idx] = 6

    elite_size = min(max(round_half_up(n * 0.01), 10), upper_half_size)

    if n <= 100:
        if elite_size >= 1:
            scores[0] = 8
        for idx in range(1, min(5, elite_size)):
            scores[idx] = 7
        for idx in range(5, elite_size):
            scores[idx] = 6
    elif n <= 1000:
        if elite_size >= 1:
            scores[0] = 9
        for idx in range(1, min(3, elite_size)):
            scores[idx] = 8
        for idx in range(3, min(5, elite_size)):
            scores[idx] = 7
        for idx in range(5, elite_size):
            scores[idx] = 6
    else:
        for idx in range(0, min(3, elite_size)):
            scores[idx] = 9
        if elite_size <= 10:
            for idx in range(3, max(3, elite_size - 1)):
                scores[idx] = 8
            if elite_size >= 10:
                scores[elite_size - 1] = 7
            elif elite_size > 3:
                scores[elite_size - 1] = 7
        else:
            for idx in range(3, min(10, elite_size)):
                scores[idx] = 8
            for idx in range(10, elite_size):
                scores[idx] = 7

    # Final safety net: no item without score, no score 10 in hard mode.
    result: list[int] = []
    for idx, score in enumerate(scores):
        if score is None:
            score = 6 if idx < upper_half_size else 4
        result.append(min(int(score), 9))
    return result


def hard_distribution(n: int) -> dict[int, int]:
    distribution = {score: 0 for score in range(1, 10)}
    for score in hard_scores_for_size(n):
        distribution[score] += 1
    return distribution


def apply_hard_scores(ranking: list[RankedItem]) -> list[RankedItem]:
    scores = hard_scores_for_size(len(ranking))
    for ranked, score in zip(ranking, scores):
        ranked.item.new_score = score
    return ranking
