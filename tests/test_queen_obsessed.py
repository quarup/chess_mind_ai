import chess

from chess_mind_ai.readonly_board import ReadOnlyBoard
from chess_mind_ai.scorers import queen_obsessed


def ctx(fen: str, own_color: chess.Color = chess.WHITE) -> ReadOnlyBoard:
    return ReadOnlyBoard(chess.Board(fen), own_color)


def test_queen_capture_outranks_non_queen_capture():
    # Position where both Qxf7+ and Bxf7+ are possible.
    # Italian-style position: white Bc4, white Qh5, black pawn f7.
    board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 0 1")
    queen_capture = chess.Move.from_uci("h5f7")
    bishop_capture = chess.Move.from_uci("c4f7")
    c = ReadOnlyBoard(board, chess.WHITE)
    queen_score = queen_obsessed.action_score(c, queen_capture)
    bishop_score = queen_obsessed.action_score(c, bishop_capture)
    assert queen_score > bishop_score


def test_hanging_queen_punished():
    # Empty-ish board: white queen can go to a square attacked by black pawn, undefended.
    board = chess.Board("4k3/4p3/8/8/8/8/4K3/3Q4 w - - 0 1")
    hang_move = chess.Move.from_uci("d1d6")  # attacked by e7 pawn, undefended
    safe_move = chess.Move.from_uci("d1d3")
    c = ReadOnlyBoard(board, chess.WHITE)
    assert queen_obsessed.action_score(c, hang_move) < queen_obsessed.action_score(c, safe_move)


def test_queen_check_outranks_quiet_queen_move():
    # Black king on h8 (far corner), white queen on a1.
    # Qa8+ checks along the 8th rank from a8; queen lands far from the king,
    # so we get the check bonus without the trade-of-piece penalty.
    board = chess.Board("7k/8/8/8/8/8/4K3/Q7 w - - 0 1")
    check = chess.Move.from_uci("a1a8")
    quiet = chess.Move.from_uci("a1a4")
    c = ReadOnlyBoard(board, chess.WHITE)
    assert queen_obsessed.action_score(c, check) > queen_obsessed.action_score(c, quiet)


def test_state_score_rewards_central_active_queen():
    central = ctx("4k3/8/8/8/3Q4/8/8/4K3 w - - 0 1")
    corner = ctx("4k3/8/8/8/8/8/8/Q3K3 w - - 0 1")
    assert queen_obsessed.state_score(central) > queen_obsessed.state_score(corner)


def test_trajectory_score_punishes_losing_queen():
    with_queen = ctx("4k3/8/8/8/8/8/4K3/3Q4 w - - 0 1")
    without_queen = ctx("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    with_score = queen_obsessed.trajectory_score(with_queen)
    without_score = queen_obsessed.trajectory_score(without_queen)
    assert with_score > without_score


def test_trajectory_rewards_queen_move_history():
    moves = [
        chess.Move.from_uci("e2e4"),
        chess.Move.from_uci("e7e5"),
        chess.Move.from_uci("d1h5"),
        chess.Move.from_uci("b8c6"),
    ]
    board = chess.Board()
    for m in moves:
        board.push(m)
    queen_active = ReadOnlyBoard(board, chess.WHITE)

    quiet_board = chess.Board()
    for m in [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")]:
        quiet_board.push(m)
    quiet_ctx = ReadOnlyBoard(quiet_board, chess.WHITE)

    active_score = queen_obsessed.trajectory_score(queen_active)
    quiet_score = queen_obsessed.trajectory_score(quiet_ctx)
    assert active_score > quiet_score
