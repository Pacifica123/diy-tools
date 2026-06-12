from __future__ import annotations

from app.domain.models import ScoreMode
from app.domain.ranking import RankedItem
from app.domain.scoring_hard import apply_hard_scores
from app.domain.scoring_light import apply_light_scores


def apply_scores(ranking: list[RankedItem], mode: ScoreMode) -> list[RankedItem]:
    if mode == "hard":
        return apply_hard_scores(ranking)
    return apply_light_scores(ranking)
