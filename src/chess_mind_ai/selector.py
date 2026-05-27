"""Combine engine score and style score, filter by Elo centipawn budget, pick a move.

Implements the selection process from plan.md sections 4 and 9.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

import chess

from chess_mind_ai.elo import blunder_budget_cp, noise_amplitude
from chess_mind_ai.engine import ChessEngine
from chess_mind_ai.readonly_board import ReadOnlyBoard


class StyleScorer(Protocol):
    def action_score(self, ctx: ReadOnlyBoard, move: chess.Move) -> float: ...
    def state_score(self, ctx: ReadOnlyBoard) -> float: ...
    def trajectory_score(self, ctx: ReadOnlyBoard) -> float: ...


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


def _score_triples_in_process(
    scorer: StyleScorer,
    board: chess.Board,
    own_color: chess.Color,
    moves: list[chess.Move],
) -> list[tuple[float, float, float]]:
    # The before-position is the same for every candidate, so build it once;
    # peek(move) gives each candidate's after-position. Mirrors the worker.
    ctx_before = ReadOnlyBoard(board, own_color)
    triples: list[tuple[float, float, float]] = []
    for move in moves:
        ctx_after = ctx_before.peek(move)
        action = scorer.action_score(ctx_before, move)
        state = scorer.state_score(ctx_after)
        trajectory = scorer.trajectory_score(ctx_after)
        triples.append((action, state, trajectory))
    return triples


def _combine_and_select(
    candidates: list,
    triples: list[tuple[float, float, float]],
    target_elo: int,
    style_weight: float,
    rng: random.Random | None,
) -> tuple[chess.Move | None, list[MoveBreakdown]]:
    """Combine engine cp scores with per-candidate style triples, filter by the
    Elo blunder budget, and pick the highest-scoring allowed move.

    Shared by the in-process (`select_move`) and sandboxed
    (`select_move_sandboxed`) paths so selection logic lives in one place.
    """
    if not candidates:
        return None, []

    rng = rng or random.Random()
    budget = blunder_budget_cp(target_elo)
    noise_amp = noise_amplitude(target_elo)
    best_cp = max(c.cp_score for c in candidates)

    breakdowns: list[MoveBreakdown] = []
    for candidate, (action, state, trajectory) in zip(candidates, triples, strict=True):
        allowed = candidate.cp_score >= best_cp - budget
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


def select_move(
    engine: ChessEngine,
    scorer: StyleScorer,
    board: chess.Board,
    target_elo: int,
    own_color: chess.Color,
    style_weight: float = 30.0,
    rng: random.Random | None = None,
) -> tuple[chess.Move | None, list[MoveBreakdown]]:
    """Return (best_move, full_breakdown) using an in-process (trusted) scorer.

    Style scores are roughly in [-10, 10] units; engine scores are centipawns.
    The default style_weight of 30 means one "style unit" is worth ~30cp — large
    enough that style can meaningfully override engine preferences within the
    Elo blunder budget (e.g. 218cp at Elo 1500), while still being filtered out
    at high Elo where the budget is tight (50cp at 2200).
    """
    candidates = engine.top_candidates(board)
    if not candidates:
        return None, []
    triples = _score_triples_in_process(
        scorer, board, own_color, [c.move for c in candidates]
    )
    return _combine_and_select(candidates, triples, target_elo, style_weight, rng)


def select_move_sandboxed(
    engine: ChessEngine,
    source: str,
    board: chess.Board,
    target_elo: int,
    own_color: chess.Color,
    style_weight: float = 30.0,
    rng: random.Random | None = None,
    **sandbox_kwargs,
) -> tuple[chess.Move | None, list[MoveBreakdown]]:
    """Like `select_move`, but the (untrusted) scorer `source` is executed in an
    isolated worker process. On any sandbox failure we fall back to a neutral
    all-zero style score — i.e. pure engine play at the target Elo — rather than
    aborting the game (plan §14, "always have a neutral fallback").
    """
    from chess_mind_ai.sandbox.worker import score_candidates_sandboxed

    candidates = engine.top_candidates(board)
    if not candidates:
        return None, []
    moves = [c.move for c in candidates]
    triples = score_candidates_sandboxed(
        source, board, own_color, moves, **sandbox_kwargs
    )
    if triples is None:
        triples = [(0.0, 0.0, 0.0)] * len(candidates)
    return _combine_and_select(candidates, triples, target_elo, style_weight, rng)
