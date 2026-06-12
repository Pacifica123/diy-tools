from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.parser import parse_title_file
from app.domain.ranking import build_ranking
from app.domain.scoring import apply_scores
from app.domain.scoring_hard import hard_distribution
from app.domain.scoring_light import light_distribution
from app.domain.tournament import TournamentEngine


def choose_by_old_score(engine: TournamentEngine) -> None:
    match = engine.current_match()
    if match is None:
        return
    left = engine.get_item(match.left_id)
    right = engine.get_item(match.right_id) if match.right_id is not None else None
    if right is None:
        return
    left_score = float(left.old_score or 0)
    right_score = float(right.old_score or 0)
    engine.select_winner(left.id if left_score >= right_score else right.id)


def main() -> int:
    sample = ROOT / "examples" / "sample_input.txt"
    parsed = parse_title_file(sample)
    assert len(parsed.items) == 9, f"Expected 9 items, got {len(parsed.items)}"
    assert parsed.items[6].comment, "Comment line should be parsed"

    engine = TournamentEngine.new(parsed.items, mode="light", random_seed=42)
    while not engine.is_finished():
        choose_by_old_score(engine)

    ranking = apply_scores(build_ranking(engine.state), "light")
    assert len(ranking) == len(parsed.items)
    assert all(item.item.new_score is not None for item in ranking)
    assert sum(light_distribution(87).values()) == 87
    assert light_distribution(87) == {10: 1, 9: 8, 8: 8, 7: 18, 6: 26, 5: 26}
    assert sum(hard_distribution(87).values()) == 87
    assert hard_distribution(87).get(10, 0) == 0
    assert max(hard_distribution(87).keys()) <= 9

    print("OK: parser, tournament, ranking and scoring smoke test passed")
    print("Champion:", ranking[0].item.title)
    print("Light distribution for sample:", {s: sum(1 for r in ranking if r.item.new_score == s) for s in range(10, 4, -1)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
