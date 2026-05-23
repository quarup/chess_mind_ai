"""Combine engine score and style score, filter by Elo centipawn budget, pick a move.

Implements the selection process from plan.md sections 4 and 9.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

import chess

from chess_mind_ai.context import SafeChessContext
from chess_mind_ai.elo import blunder_budget_cp, noise_amplitude
from chess_mind_ai.engine import ChessEngine


class StyleScorer(Protocol):
    def action_score(self, ctx: SafeChessContext, move: chess.Move) -> float: ...
    def state_score(self, ctx: SafeChessContext) -> float: ...
    def trajectory_score(self, ctx: SafeChessContext) -> float: ...


@dataclass(frozen=True)
class MoveBreakdown:
    move: chess.Move
    cp_score: int
    action: float
    state: float
    trajectory: float
    style: float
    noise: float
    total: float
    allowed: bool  # within Elo blunder budget

    def san(self, board: chess.Board) -> str:
        return board.san(self.move)


def select_move(
    engine: ChessEngine,
    scorer: StyleScorer,
    board: chess.Board,
    target_elo: int,
    own_color: chess.Color,
    style_weight: float = 30.0,
    rng: random.Random | None = None,
) -> tuple[chess.Move | None, list[MoveBreakdown]]:
    """Return (best_move, full_breakdown).

    Style scores are roughly in [-10, 10] units; engine scores are centipawns.
    The default style_weight of 30 means one "style unit" is worth ~30cp — large
    enough that style can meaningfully override engine preferences within the
    Elo blunder budget (e.g. 218cp at Elo 1500), while still being filtered out
    at high Elo where the budget is tight (50cp at 2200).
    """
    candidates = engine.top_candidates(board)
    if not candidates:
        return None, []

    rng = rng or random.Random()
    budget = blunder_budget_cp(target_elo)
    noise_amp = noise_amplitude(target_elo)
    best_cp = max(c.cp_score for c in candidates)

    breakdowns: list[MoveBreakdown] = []
    for candidate in candidates:
        allowed = candidate.cp_score >= best_cp - budget

        ctx_before = SafeChessContext(board, own_color)
        board_after = board.copy()
        board_after.push(candidate.move)
        ctx_after = SafeChessContext(board_after, own_color)

        action = scorer.action_score(ctx_before, candidate.move)
        state = scorer.state_score(ctx_after)
        trajectory = scorer.trajectory_score(ctx_after)
        style = action + state + trajectory

        noise = rng.uniform(-noise_amp, noise_amp)
        total = candidate.cp_score + style_weight * style + noise

        breakdowns.append(
            MoveBreakdown(
                move=candidate.move,
                cp_score=candidate.cp_score,
                action=action,
                state=state,
                trajectory=trajectory,
                style=style,
                noise=noise,
                total=total,
                allowed=allowed,
            )
        )

    allowed_breakdowns = [b for b in breakdowns if b.allowed]
    pool = allowed_breakdowns or breakdowns  # safety fallback
    chosen = max(pool, key=lambda b: b.total)
    return chosen.move, breakdowns
