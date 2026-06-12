from __future__ import annotations

import math


def round_half_up(value: float) -> int:
    """Round 0.5 upward instead of Python's bankers rounding."""
    if value < 0:
        return -int(abs(value) + 0.5)
    return int(value + 0.5)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def safe_count(value: int, remaining: int) -> int:
    return clamp(value, 0, max(0, remaining))


def ceil_div2(value: int) -> int:
    return math.ceil(value / 2)
