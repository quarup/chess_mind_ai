from __future__ import annotations

import argparse
import sys

import chess

from chess_mind_ai.elo import candidate_count
from chess_mind_ai.engine import ChessEngine
from chess_mind_ai.scorers import queen_obsessed
from chess_mind_ai.selector import MoveBreakdown, select_move


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chess-mind-ai",
        description="Play against ChessMind AI in the terminal.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="Play a game against the AI in the terminal.")
    play.add_argument("--color", choices=["white", "black"], default="white",
                      help="Which color you play (default: white).")
    play.add_argument("--elo", type=int, default=1500,
                      help="Target rating for the AI (default: 1500).")
    play.add_argument("--prompt", type=str, default=None,
                      help="Reserved for M3+; currently ignored (always queen-obsessed).")
    play.add_argument("--explain", action="store_true",
                      help="Print per-candidate score breakdown each AI move.")
    play.add_argument("--stockfish", default="stockfish",
                      help="Path to the Stockfish binary (default: stockfish on PATH).")
    play.add_argument("--multipv", type=int, default=None,
                      help="Number of candidate moves Stockfish returns. "
                           "Default scales with --elo (more candidates at lower Elo).")
    play.add_argument("--movetime", type=int, default=1000,
                      help="Stockfish thinking time per move, in ms (default: 1000).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "play":
        return _play(args)
    return 1


def _play(args: argparse.Namespace) -> int:
    human_color = chess.WHITE if args.color == "white" else chess.BLACK
    ai_color = not human_color

    if args.prompt:
        print(
            "Note: --prompt is reserved for a later milestone. "
            "Style is hardcoded to queen-obsessed for now.\n",
            file=sys.stderr,
        )

    multipv = args.multipv if args.multipv is not None else candidate_count(args.elo)
    engine = ChessEngine(
        path=args.stockfish,
        multipv=multipv,
        movetime_ms=args.movetime,
    )
    board = chess.Board()

    print(f"You are {'white' if human_color == chess.WHITE else 'black'}. "
          f"AI target Elo: {args.elo}. Style: queen-obsessed.")
    print("Type SAN moves (e.g. 'e4', 'Nf3', 'O-O') or 'quit' to exit.\n")

    try:
        while not board.is_game_over():
            _print_board(board)
            if board.turn == human_color:
                move = _read_human_move(board)
                if move is None:
                    print("Goodbye.")
                    return 0
            else:
                move, breakdown = select_move(
                    engine, queen_obsessed, board, args.elo, ai_color,
                )
                if move is None:
                    print("AI returned no move; aborting.")
                    return 1
                if args.explain:
                    _print_breakdown(board, breakdown, chosen=move)
                print(f"AI plays: {board.san(move)}\n")

            board.push(move)

        _print_board(board)
        outcome = board.outcome()
        termination = outcome.termination.name if outcome else "UNKNOWN"
        print(f"\nGame over: {board.result()} ({termination})")
        return 0
    finally:
        engine.close()


def _print_board(board: chess.Board) -> None:
    print()
    print(board.unicode(borders=True, empty_square=" "))
    print()


def _read_human_move(board: chess.Board) -> chess.Move | None:
    while True:
        try:
            text = input("Your move: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not text:
            continue
        if text.lower() in {"quit", "exit", "q"}:
            return None
        try:
            return board.parse_san(text)
        except (ValueError, chess.IllegalMoveError, chess.InvalidMoveError,
                chess.AmbiguousMoveError) as e:
            print(f"  invalid move: {e}. try again.")


def _print_breakdown(board: chess.Board, breakdowns: list[MoveBreakdown],
                     chosen: chess.Move) -> None:
    print("  candidates (sorted by total score):")
    print(f"  {'move':>6}  {'cp':>7}  {'action':>7}  {'state':>7}  "
          f"{'traj':>7}  {'noise':>7}  {'total':>9}  status")
    for b in sorted(breakdowns, key=lambda b: -b.total):
        san = board.san(b.move)
        marker = " <- chosen" if b.move == chosen else ""
        budget_tag = "" if b.allowed else " (over budget)"
        print(f"  {san:>6}  {b.cp_score:>7}  {b.action:>7.2f}  {b.state:>7.2f}  "
              f"{b.trajectory:>7.2f}  {b.noise:>7.2f}  {b.total:>9.2f}"
              f"{budget_tag}{marker}")


if __name__ == "__main__":
    sys.exit(main())
