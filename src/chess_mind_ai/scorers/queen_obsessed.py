"""Hand-coded 'queen-obsessed' style scorer (ReadOnlyBoard API).

Mirrors the example in plan.md section 5. Reward moving / capturing / checking
with the queen; punish hanging or trading the queen; reward queen activity in
the resulting position; reward a history of queen-led play.

`ctx` is a `ReadOnlyBoard`. For `action_score` it is the position *before*
`move`; `ctx.peek(move)` gives a read-only view of the position *after* it (used
here for hang/trade checks). For `state_score`/`trajectory_score` it is the
position after the move. The three public functions match the LLM-generated
scorer contract so the rest of the pipeline treats hand-coded and generated
scorers identically.
"""
from __future__ import annotations

import chess

from chess_mind_ai.readonly_board import ReadOnlyBoard


def action_score(ctx: ReadOnlyBoard, move: chess.Move) -> float:
    score = 0.0
    own = ctx.own_color
    after = ctx.peek(move)

    if ctx.moving_piece_type(move) == chess.QUEEN:
        score += 1.2
        if ctx.is_capture(move):
            score += 0.9
        if ctx.gives_check(move):
            score += 0.8
        enemy_king = ctx.king(not own)
        if enemy_king is not None and chess.square_distance(move.to_square, enemy_king) <= 2:
            score += 0.5
        if after.is_attacked_by(not own, move.to_square):  # lands on an attacked square
            score -= 2.5

    # Penalize leaving any own queen attacked and undefended after the move.
    for sq in after.squares_with(chess.QUEEN, own):
        if after.is_attacked_by(not own, sq) and not after.attackers(own, sq):
            score -= 2.0

    return score


def state_score(ctx: ReadOnlyBoard) -> float:
    own = ctx.own_color
    mobility = 0.0
    pressure = 0.0
    centralization = 0.0
    under_attack = 0.0

    queens = ctx.squares_with(chess.QUEEN, own)
    for sq in queens:
        for target in ctx.attacks(sq):
            color = ctx.color_at(target)
            if color != own:  # empty or enemy square the queen could move to
                mobility += 1.0
            if color == (not own):  # enemy piece the queen bears down on
                pressure += 1.0
        file_dist = abs(chess.square_file(sq) - 3.5)
        rank_dist = abs(chess.square_rank(sq) - 3.5)
        centralization += 1.0 - ((file_dist + rank_dist) / 7.0)
        if ctx.is_attacked_by(not own, sq):
            under_attack += 1.0

    if queens:
        centralization /= len(queens)

    return 0.7 * mobility + 0.8 * pressure + 0.5 * centralization - 1.2 * under_attack


def trajectory_score(ctx: ReadOnlyBoard) -> float:
    own = ctx.own_color
    score = 0.3 * min(ctx.own_move_count(chess.QUEEN), 5)
    if not ctx.has_piece(chess.QUEEN, own):
        score -= 5.0
    return score
