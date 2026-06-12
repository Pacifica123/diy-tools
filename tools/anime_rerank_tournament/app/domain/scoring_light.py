from __future__ import annotations

import math

from app.domain.ranking import RankedItem
from app.utils.rounding import round_half_up


def light_distribution(n: int) -> dict[int, int]:
    if n <= 0:
        return {10: 0, 9: 0, 8: 0, 7: 0, 6: 0, 5: 0}

    top_1 = round_half_up(n * 0.01)
    top_10 = max(top_1, round_half_up(n * 0.10))
    top_20 = max(top_10, round_half_up(n * 0.20))
    top_40 = max(top_20, round_half_up(n * 0.40))

    top_1 = min(top_1, n)
    top_10 = min(top_10, n)
    top_20 = min(top_20, n)
    top_40 = min(top_40, n)

    count_10 = top_1
    count_9 = max(0, top_10 - top_1)
    count_8 = max(0, top_20 - top_10)
    count_7 = max(0, top_40 - top_20)
    remaining = max(0, n - top_40)
    count_6 = math.ceil(remaining / 2)
    count_5 = remaining - count_6

    return {10: count_10, 9: count_9, 8: count_8, 7: count_7, 6: count_6, 5: count_5}


def apply_light_scores(ranking: list[RankedItem]) -> list[RankedItem]:
    distribution = light_distribution(len(ranking))
    index = 0
    for score in (10, 9, 8, 7, 6, 5):
        for _ in range(distribution.get(score, 0)):
            if index >= len(ranking):
                break
            ranking[index].item.new_score = score
            index += 1
    while index < len(ranking):
        ranking[index].item.new_score = 5
        index += 1
    return ranking
