"""Hand-coded 'queen-obsessed' style scorer.

Mirrors the example in plan.md section 5. Reward moving / capturing / checking
with the queen; punish hanging or trading the queen; reward queen activity in
the resulting position; reward a history of queen-led play.

The three public functions match the LLM-generated scorer contract
(action_score, state_score, trajectory_score) so the rest of the pipeline can
treat hand-coded and generated scorers identically.
"""
from __future__ import annotations

import chess

from chess_mind_ai.context import SafeChessContext


def action_score(ctx: SafeChessContext, move: chess.Move) -> float:
    score = 0.0

    if ctx.moving_piece_is(move, "queen"):
        score += 1.2
        if ctx.is_capture(move):
            score += 0.9
        if ctx.gives_check(move):
            score += 0.8
        if ctx.destination_near_enemy_king(move):
            score += 0.5

    if ctx.causes_trade_of_piece(move, "queen"):
        score -= 2.5

    if ctx.hangs_piece_after_move(move, "queen"):
        score -= 2.0

    return score


def state_score(ctx: SafeChessContext) -> float:
    score = 0.0
    score += 0.7 * ctx.piece_mobility("queen")
    score += 0.8 * ctx.piece_attack_pressure("queen")
    score += 0.5 * ctx.piece_centralization("queen")
    score -= 1.2 * ctx.piece_under_attack("queen")
    return score


def trajectory_score(ctx: SafeChessContext) -> float:
    score = 0.0
    queen_moves = ctx.count_own_moves_by_piece("queen")
    score += min(queen_moves, 5) * 0.3
    if ctx.own_queen_was_traded():
        score -= 5.0
    return score
