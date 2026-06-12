from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import TitleItem, TournamentState


@dataclass
class RankedItem:
    rank: int
    item: TitleItem
    lost_to_title: str | None = None


def build_ranking(state: TournamentState) -> list[RankedItem]:
    """Build a heuristic full ranking after a single-elimination tournament.

    The champion is exact. Other places are estimated by elimination round,
    strength of the opponent who eliminated the item, wins, old score and source order.
    """
    items_by_id = {item.id: item for item in state.items}
    champion_id = state.active_ids[0] if state.active_ids and state.status == "finished" else None

    def old_score(item: TitleItem) -> float:
        return float(item.old_score or 0)

    # Preliminary order, used to estimate the strength of the eliminator.
    preliminary = sorted(
        state.items,
        key=lambda item: (
            0 if item.id == champion_id else 1,
            -(item.eliminated_round or 10**9),
            -item.wins,
            -old_score(item),
            item.source_index,
        ),
    )
    prelim_rank = {item.id: index + 1 for index, item in enumerate(preliminary)}

    def lost_to_rank(item: TitleItem) -> int:
        if item.lost_to_id is None:
            return 0
        return prelim_rank.get(item.lost_to_id, 10**9)

    ordered = sorted(
        state.items,
        key=lambda item: (
            0 if item.id == champion_id else 1,
            -(item.eliminated_round or 10**9),
            lost_to_rank(item),
            -item.wins,
            -old_score(item),
            item.source_index,
        ),
    )

    ranked: list[RankedItem] = []
    for index, item in enumerate(ordered, start=1):
        lost_to = items_by_id.get(item.lost_to_id).title if item.lost_to_id in items_by_id else None
        ranked.append(RankedItem(rank=index, item=item, lost_to_title=lost_to))
    return ranked
