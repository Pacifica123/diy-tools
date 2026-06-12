from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.domain.models import SpinOptions
from app.domain.parser import parse_wheel_text
from app.domain.wheel import WheelEngine


def main() -> int:
    text = """
    весь день в шахматы (минимум 12 часов чисто игры) : 10
    весь день программирование (минимум 12 часов чисто разработки) : 20
    день чтения : 5
    """
    result = parse_wheel_text(text)
    assert len(result.items) == 3, result.items
    assert not result.issues, result.issues

    equal_engine = WheelEngine.new(result.items, SpinOptions(mode="equal", random_seed=42))
    equal_segments = equal_engine.segments()
    assert len(equal_segments) == 3
    assert all(abs(s.span - 120.0) < 0.0001 for s in equal_segments), equal_segments

    weighted_engine = WheelEngine.new(result.items, SpinOptions(mode="weighted", random_seed=42))
    weighted_segments = weighted_engine.segments()
    spans = [s.span for s in weighted_segments]
    assert abs(spans[1] / spans[0] - 2.0) < 0.0001, spans

    item, weight, total = weighted_engine.select_item()
    record = weighted_engine.record_spin(item, weight, total)
    assert record.total_weight == 35
    assert len(weighted_engine.session.history) == 1

    print("Smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
