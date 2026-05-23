import chess
import pytest

from chess_mind_ai.context import SafeChessContext


def ctx(fen: str, own_color: chess.Color = chess.WHITE) -> SafeChessContext:
    return SafeChessContext(chess.Board(fen), own_color)


def test_moving_piece_is_detects_queen():
    # White queen on d1, white to move
    c = ctx("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    move = chess.Move.from_uci("d1d3")  # not legal but moving_piece_is doesn't care
    assert c.moving_piece_is(move, "queen")
    pawn_move = chess.Move.from_uci("e2e4")
    assert c.moving_piece_is(pawn_move, "pawn")
    assert not c.moving_piece_is(pawn_move, "queen")


def test_unknown_piece_name_raises():
    c = ctx(chess.STARTING_FEN)
    with pytest.raises(ValueError):
        c.moving_piece_is(chess.Move.from_uci("e2e4"), "duck")


def test_is_capture_and_gives_check():
    # White queen on h5, black pawn on f7 — Qxf7+ captures and gives check
    c = ctx("rnbqkbnr/pppp1ppp/8/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR w KQkq - 0 1")
    move = chess.Move.from_uci("h5f7")
    assert c.is_capture(move)
    assert c.gives_check(move)


def test_destination_near_enemy_king():
    # White queen on a1, black king on h8. d4 is far; g7 is adjacent.
    c = ctx("7k/8/8/8/8/8/8/Q6K w - - 0 1", own_color=chess.WHITE)
    far = chess.Move.from_uci("a1d4")
    close = chess.Move.from_uci("a1g7")
    assert not c.destination_near_enemy_king(far)
    assert c.destination_near_enemy_king(close)


def test_hangs_piece_after_move_on_undefended_queen():
    # White queen moves to a square attacked by black pawn, undefended
    c = ctx("4k3/4p3/8/8/8/8/4K3/3Q4 w - - 0 1")
    move = chess.Move.from_uci("d1d6")  # queen to d6, attacked by e7-pawn, undefended
    assert c.hangs_piece_after_move(move, "queen")


def test_does_not_hang_when_defended():
    # White queen on d1; supported by rook on d2. d1 itself is "safe"; we pick
    # a move where the queen lands on a square attacked but defended.
    # White queen d4 attacked by black pawn e5, defended by white rook a4.
    c = ctx("4k3/8/8/4p3/R7/8/4K3/3Q4 w - - 0 1")
    move = chess.Move.from_uci("d1d4")
    # d4 attacked by e5 pawn, defended by a4 rook -> not "hanging" per our heuristic
    assert not c.hangs_piece_after_move(move, "queen")


def test_piece_centralization_more_for_central_queen():
    central = ctx("4k3/8/8/8/3Q4/8/8/4K3 w - - 0 1")
    corner = ctx("4k3/8/8/8/8/8/8/Q3K3 w - - 0 1")
    assert central.piece_centralization("queen") > corner.piece_centralization("queen")


def test_own_queen_was_traded():
    has_queen = ctx(chess.STARTING_FEN)
    no_queen = ctx("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    assert not has_queen.own_queen_was_traded()
    assert no_queen.own_queen_was_traded()


def test_count_own_moves_by_piece_replays_move_stack():
    # Simulate: 1. e4 e5 2. Qh5 Nc6 3. Qxe5+
    moves = [
        chess.Move.from_uci("e2e4"),
        chess.Move.from_uci("e7e5"),
        chess.Move.from_uci("d1h5"),
        chess.Move.from_uci("b8c6"),
        chess.Move.from_uci("h5e5"),
    ]
    board = chess.Board()
    for m in moves:
        board.push(m)
    c = SafeChessContext(board, chess.WHITE)
    assert c.count_own_moves_by_piece("queen") == 2
    assert c.count_own_moves_by_piece("pawn") == 1
    # Black's perspective should see only their moves
    c_black = SafeChessContext(board, chess.BLACK)
    assert c_black.count_own_moves_by_piece("pawn") == 1
    assert c_black.count_own_moves_by_piece("knight") == 1


def test_count_moves_zero_for_fen_loaded_board_with_no_history():
    # Board loaded from FEN has an empty move_stack — no history to count.
    c = ctx("4k3/8/8/8/3Q4/8/8/4K3 w - - 0 1")
    assert c.count_own_moves_by_piece("queen") == 0


def test_piece_mobility_uses_own_color_regardless_of_turn():
    # Black to move, but we're asking about white's queen mobility
    c = ctx("4k3/8/8/8/3Q4/8/8/4K3 b - - 0 1", own_color=chess.WHITE)
    # Queen on d4 has many moves; just check it's > 0
    assert c.piece_mobility("queen") > 10


def test_piece_under_attack():
    # White queen on d4 attacked by black pawn on e5
    c = ctx("4k3/8/8/4p3/3Q4/8/8/4K3 w - - 0 1")
    assert c.piece_under_attack("queen") == 1
    # No attack on king from this layout
    assert c.piece_under_attack("king") == 0
