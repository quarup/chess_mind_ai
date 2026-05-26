from __future__ import annotations

import argparse
import sys

import chess

from chess_mind_ai.elo import candidate_count
from chess_mind_ai.engine import ChessEngine
from chess_mind_ai.scorers import queen_obsessed
from chess_mind_ai.selector import (
    MoveBreakdown,
    StyleScorer,
    select_move,
    select_move_sandboxed,
)


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
                      help="Natural-language style description. If given, an LLM "
                           "generates the scorer code. Otherwise the hand-coded "
                           "queen-obsessed scorer is used. Requires GEMINI_API_KEY.")
    play.add_argument("--llm-model", type=str, default=None,
                      help="Override the Gemini model (default: gemini-2.5-flash-lite).")
    play.add_argument("--show-generated-code", action="store_true",
                      help="Print the LLM-generated scorer source before the game starts.")
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

    scorer, source, style_label = _build_scorer(args)

    multipv = args.multipv if args.multipv is not None else candidate_count(args.elo)
    engine = ChessEngine(
        path=args.stockfish,
        multipv=multipv,
        movetime_ms=args.movetime,
    )
    board = chess.Board()

    print(f"You are {'white' if human_color == chess.WHITE else 'black'}. "
          f"AI target Elo: {args.elo}. Style: {style_label}.")
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
                if source is not None:
                    move, breakdown = select_move_sandboxed(
                        engine, source, board, args.elo, ai_color,
                    )
                else:
                    move, breakdown = select_move(
                        engine, scorer, board, args.elo, ai_color,
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


def _build_scorer(
    args: argparse.Namespace,
) -> tuple[StyleScorer | None, str | None, str]:
    """Return (in_process_scorer, generated_source, label).

    Exactly one of (scorer, source) is set. With no --prompt we use the trusted
    hand-coded queen-obsessed scorer in-process. With a prompt, we ask Gemini for
    scorer code, validate it on sample positions, and return the *source* to be
    executed in the sandbox worker — generated code is never run in-process. If
    every generation attempt fails the sample-position gate we fall back to a
    neutral in-process scorer (pure engine play); and if the sandbox later fails
    on an accepted source mid-game, the selector still falls back to neutral per
    move (it does not abort).
    """
    if not args.prompt:
        return queen_obsessed, None, "queen-obsessed (hand-coded)"

    from chess_mind_ai.llm.gemini import DEFAULT_MODEL, GeminiProvider
    from chess_mind_ai.llm.prompt import SYSTEM_PROMPT, extract_code
    from chess_mind_ai.sandbox.validation import (
        ValidationResult,
        generate_and_validate,
    )
    from chess_mind_ai.scorers import neutral

    model = args.llm_model or DEFAULT_MODEL
    provider = GeminiProvider(model=model)
    print(f"Asking {model} for a scorer matching: {args.prompt!r}", file=sys.stderr)

    def _generate() -> str:
        raw = provider.generate(system=SYSTEM_PROMPT, user=args.prompt)
        code = extract_code(raw)
        if args.show_generated_code:
            print("\n--- generated scorer ---\n", file=sys.stderr)
            print(code, file=sys.stderr)
            print("\n--- end generated scorer ---\n", file=sys.stderr)
        return code

    def _on_reject(attempt: int, result: ValidationResult) -> None:
        print(f"  scorer rejected (attempt {attempt}): {result.reason}; "
              f"regenerating...", file=sys.stderr)

    print("Validating generated scorer on sample positions...", file=sys.stderr)
    source = generate_and_validate(_generate, on_reject=_on_reject)
    if source is not None:
        return None, source, f"prompt-driven ({model}, sandboxed)"

    print("All generation attempts failed validation; falling back to neutral "
          "engine play.", file=sys.stderr)
    return neutral, None, "neutral fallback (generation failed validation)"


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
