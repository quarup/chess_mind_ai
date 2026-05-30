from __future__ import annotations

import chess

from chess_mind_ai.persona.narration import (
    describe_move,
    digest,
    is_dramatic,
)
from chess_mind_ai.selector import MoveBreakdown


def _bd(move: chess.Move, cp: int, *, allowed: bool = True, style: float = 0.0):
    return MoveBreakdown(
        move=move,
        cp_score=cp,
        action=0.0,
        state=0.0,
        trajectory=0.0,
        style=style,
        noise=0.0,
        total=float(cp),
        allowed=allowed,
    )


def test_quiet_developing_move_is_not_dramatic():
    board = chess.Board()
    move = chess.Move.from_uci("g1f3")  # Nf3, quiet
    moment = describe_move(board, move, [_bd(move, 20)], chess.WHITE)
    assert moment.moving_piece == "knight"
    assert not moment.is_capture
    assert moment.events == ()
    assert not is_dramatic(moment)


def test_check_is_dramatic_and_in_digest():
    # Scholar's-mate-ish position where Qxf7 is checkmate.
    board = chess.Board(
        "r1bqkbnr/pppp1Qpp/2n5/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"
    )
    # That FEN already has the queen on f7 delivering mate; build the move instead.
    board = chess.Board(
        "r1bqkbnr/pppp1ppp/2n5/2b1p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    )
    move = board.parse_san("Qxf7#")
    moment = describe_move(board, move, [_bd(move, 10000)], chess.WHITE)
    assert moment.is_checkmate
    assert moment.is_capture
    assert "captured_enemy_queen" not in moment.events  # captured a pawn
    assert "checkmate" in moment.events
    assert is_dramatic(moment)
    text = digest(moment)
    assert "CHECKMATE" in text
    assert "Qxf7" in text


def test_capturing_the_enemy_queen_is_flagged():
    # White queen on d1 can take black queen on d8 down the open d-file.
    board = chess.Board("3qk3/8/8/8/8/8/8/3QK3 w - - 0 1")
    move = board.parse_san("Qxd8+")
    moment = describe_move(board, move, [_bd(move, 900)], chess.WHITE)
    assert moment.captured_piece == "queen"
    assert "captured_enemy_queen" in moment.events
    assert moment.gives_check
    assert is_dramatic(moment)


def test_own_queen_left_hanging_is_flagged():
    # White queen moves to a square attacked by the black queen, undefended.
    board = chess.Board("3qk3/8/8/8/7Q/8/8/7K w - - 0 1")
    move = board.parse_san("Qd4")  # steps onto the d-file in front of black queen
    moment = describe_move(board, move, [_bd(move, -400)], chess.WHITE)
    assert moment.own_queen_in_danger
    assert "own_queen_in_danger" in moment.events
    assert "under attack" in digest(moment)


def test_eval_swing_detected_against_prev_cp():
    board = chess.Board()
    move = chess.Move.from_uci("e2e4")
    moment = describe_move(board, move, [_bd(move, 300)], chess.WHITE, prev_cp=20)
    assert moment.eval_swing == 280
    assert "swing_up" in moment.events
    assert "big swing in your favor" in digest(moment)


def test_passed_up_alternative_mentioned():
    board = chess.Board()
    chosen = chess.Move.from_uci("e2e4")
    other = chess.Move.from_uci("d2d4")
    breakdown = [_bd(chosen, 30, style=5.0), _bd(other, 60)]
    moment = describe_move(board, chosen, breakdown, chess.WHITE)
    assert moment.passed_up is not None
    assert "d4" in moment.passed_up
    assert "+60 cp" in moment.passed_up


def test_passed_up_ignores_over_budget_alternatives():
    board = chess.Board()
    chosen = chess.Move.from_uci("e2e4")
    other = chess.Move.from_uci("d2d4")
    breakdown = [_bd(chosen, 30), _bd(other, 60, allowed=False)]
    moment = describe_move(board, chosen, breakdown, chess.WHITE)
    assert moment.passed_up is None
