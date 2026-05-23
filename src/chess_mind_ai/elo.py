"""Elo-driven knobs: centipawn budget (how far style may drift from best) and
score noise (random component, simulating low-rated decision noise).

Anchor points come from plan.md section 9. We linearly interpolate between them
so adjacent Elo values produce smooth changes.
"""
from __future__ import annotations

_BUDGET_TABLE: list[tuple[int, float]] = [
    (700, 800),
    (1000, 500),
    (1400, 250),
    (1800, 120),
    (2200, 50),
]

_NOISE_TABLE: list[tuple[int, float]] = [
    (700, 100),
    (1000, 50),
    (1400, 30),
    (1800, 15),
    (2200, 5),
]


def _interpolate(table: list[tuple[int, float]], elo: int) -> float:
    if elo <= table[0][0]:
        return table[0][1]
    if elo >= table[-1][0]:
        return table[-1][1]
    for (e0, v0), (e1, v1) in zip(table, table[1:], strict=False):
        if e0 <= elo <= e1:
            t = (elo - e0) / (e1 - e0)
            return v0 + t * (v1 - v0)
    return table[-1][1]


def blunder_budget_cp(elo: int) -> float:
    """Centipawns that style is allowed to move away from the best engine move."""
    return _interpolate(_BUDGET_TABLE, elo)


def noise_amplitude(elo: int) -> float:
    """Half-width of uniform noise added to total move score."""
    return _interpolate(_NOISE_TABLE, elo)
