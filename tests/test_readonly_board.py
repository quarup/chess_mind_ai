from __future__ import annotations

import chess
import pytest

from chess_mind_ai.readonly_board import (
    CHESS,
    ReadOnlyBoard,
    piece_type_from_name,
    scorer_globals,
)


def _board(*sans: str) -> chess.Board:
    b = chess.Board()
    for san in sans:
        b.push_san(san)
    return b


def test_is_read_only():
    rb = ReadOnlyBoard(chess.Board(), chess.WHITE)
    with pytest.raises(AttributeError):
        rb._board = None  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        rb.anything = 1  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        del rb._own_color  # type: ignore[attr-defined]


def test_does_not_share_mutable_state_with_caller():
    src = chess.Board()
    rb = ReadOnlyBoard(src, chess.WHITE)
    src.push_san("e4")  # mutate the original after construction
    # The facade kept its own copy, so the starting position is unchanged.
    assert rb.fen() == chess.STARTING_FEN
    assert rb.fullmove_number == 1


def test_basic_position_queries():
    rb = ReadOnlyBoard(chess.Board(), chess.WHITE)
    assert rb.own_color is chess.WHITE
    assert rb.turn is chess.WHITE
    assert rb.fullmove_number == 1
    assert rb.king(chess.WHITE) == chess.E1
    assert rb.piece_type_at(chess.E2) == chess.PAWN
    assert rb.color_at(chess.E2) is chess.WHITE
    assert rb.piece_at(chess.A8) == chess.Piece(chess.ROOK, chess.BLACK)
    assert rb.piece_type_at(chess.E4) is None


def test_squares_with_and_counts():
    rb = ReadOnlyBoard(chess.Board(), chess.WHITE)
    assert rb.piece_count(chess.PAWN, chess.WHITE) == 8
    assert set(rb.squares_with(chess.QUEEN, chess.BLACK)) == {chess.D8}
    assert rb.has_piece(chess.QUEEN, chess.WHITE) is True


def test_attack_maps():
    rb = ReadOnlyBoard(chess.Board(), chess.WHITE)
    # The knight on b1 attacks a3 and c3.
    assert set(rb.attacks(chess.B1)) == {chess.A3, chess.C3, chess.D2}
    # e2 pawn is defended by several white pieces.
    assert rb.is_attacked_by(chess.WHITE, chess.E2) is True
    assert chess.E1 in rb.attackers(chess.WHITE, chess.E2)


def test_move_predicates():
    # White: 1.e4 d5 — now exd5 is a capture.
    rb = ReadOnlyBoard(_board("e4", "d5"), chess.WHITE)
    capture = chess.Move.from_uci("e4d5")
    assert rb.is_legal(capture)
    assert rb.is_capture(capture)
    assert rb.moving_piece_type(capture) == chess.PAWN
    quiet = chess.Move.from_uci("g1f3")
    assert rb.is_capture(quiet) is False


def test_gives_check_detection():
    # Scholar's-mate-ish setup so a queen move gives check.
    rb = ReadOnlyBoard(_board("e4", "e5", "Qh5", "Nc6"), chess.WHITE)
    qxf7 = chess.Move.from_uci("h5f7")
    assert rb.is_capture(qxf7)
    assert rb.gives_check(qxf7)


def test_own_move_count_counts_only_own_side():
    # 1.e4 e5 2.Qh5 Nc6 3.Qf3 — white moved the queen twice.
    rb_white = ReadOnlyBoard(_board("e4", "e5", "Qh5", "Nc6", "Qf3"), chess.WHITE)
    assert rb_white.own_move_count(chess.QUEEN) == 2
    assert rb_white.own_move_count(chess.PAWN) == 1
    rb_black = ReadOnlyBoard(_board("e4", "e5", "Qh5", "Nc6", "Qf3"), chess.BLACK)
    assert rb_black.own_move_count(chess.KNIGHT) == 1
    assert rb_black.own_move_count(chess.QUEEN) == 0


def test_peek_returns_after_position_without_mutating():
    rb = ReadOnlyBoard(_board("e4", "e5"), chess.WHITE)
    qh5 = chess.Move.from_uci("d1h5")
    after = rb.peek(qh5)
    # The returned view reflects the position after the move...
    assert after.piece_type_at(chess.H5) == chess.QUEEN
    assert after.piece_type_at(chess.D1) is None
    assert after.turn is chess.BLACK
    assert after.own_color is chess.WHITE  # own_color is preserved
    # ...and peeking did not mutate the original.
    assert rb.piece_type_at(chess.D1) == chess.QUEEN
    assert rb.piece_type_at(chess.H5) is None
    assert rb.turn is chess.WHITE


def test_peek_after_position_carries_history_for_own_move_count():
    rb = ReadOnlyBoard(_board("e4", "e5"), chess.WHITE)
    after = rb.peek(chess.Move.from_uci("d1h5"))  # white's first queen move
    assert after.own_move_count(chess.QUEEN) == 1
    assert after.move_history()[-1] == chess.Move.from_uci("d1h5")


def test_move_history():
    rb = ReadOnlyBoard(_board("e4", "e5"), chess.WHITE)
    assert rb.move_history() == (
        chess.Move.from_uci("e2e4"),
        chess.Move.from_uci("e7e5"),
    )


def test_chess_namespace_constants_and_helpers():
    assert CHESS.WHITE is chess.WHITE
    assert CHESS.QUEEN == chess.QUEEN
    assert len(CHESS.SQUARES) == 64
    assert CHESS.square_file(chess.E4) == 4
    assert CHESS.square_rank(chess.E4) == 3
    assert CHESS.square_name(chess.E4) == "e4"
    assert CHESS.square_distance(chess.A1, chess.H8) == 7
    assert CHESS.parse_square("e4") == chess.E4


def test_piece_type_from_name():
    assert piece_type_from_name("Queen") == chess.QUEEN
    assert piece_type_from_name("pawn") == chess.PAWN
    with pytest.raises(ValueError, match="Unknown piece"):
        piece_type_from_name("dragon")


def test_scorer_globals_shape():
    g = scorer_globals()
    assert g["chess"] is CHESS
    assert g["piece"] is piece_type_from_name
