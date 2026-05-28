"""UCI engine interface for ChessMind AI (plan.md Milestone 5).

Makes the bot speak the Universal Chess Interface so it can plug into chess
GUIs (Cute Chess, Arena) and match runners (cutechess-cli, M6). The protocol is
a line-oriented request/response loop on stdin/stdout; see
https://gist.github.com/DOBRO/2592c6dad754ba67e6dcaec8c90165bf for the spec.

Design decisions for M5 (see the conversation that produced this milestone):

* **Config via UCI options.** Style prompt + target Elo are delivered through
  `setoption`, so they are editable inside the GUI's engine dialog. We expose
  the standard `UCI_Elo` / `UCI_LimitStrength` (which GUIs understand natively)
  plus custom `Prompt`, `Stockfish Path`, `MultiPV`, `Move Time`, `LLM Model`,
  and `Style Weight` options.

* **Eager scorer generation.** Generating a prompt-driven scorer hits the LLM
  over the network and validates on sample positions (~seconds). We do it at
  `isready` — the GUI's "are you done configuring?" checkpoint, which fires
  before the clock starts — and cache the validated source for the rest of the
  game. Generated code still runs only in the sandbox worker; on any failure we
  fall back to neutral engine play (plan §14).

* **Think time: honor explicit, else default.** On `go` we use `movetime N` if
  the GUI sends it, otherwise the `Move Time` option default (1000 ms). Full
  clock budgeting from `wtime`/`btime` is deferred to M6, where fair tournament
  time controls actually matter.

The heavy lifting (candidate generation, Elo budget, style scoring, sandboxing)
already lives in `engine`, `selector`, and `sandbox`; this module is just the
protocol shell on top, with dependency seams (`engine_factory`,
`scorer_factory`) so the command loop is testable without Stockfish or network.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TextIO

import chess

from chess_mind_ai.elo import candidate_count
from chess_mind_ai.engine import Candidate, ChessEngine
from chess_mind_ai.selector import (
    MoveBreakdown,
    StyleScorer,
    select_move,
    select_move_sandboxed,
)

ENGINE_NAME = "ChessMind AI"
ENGINE_AUTHOR = "quarup"

# "Full strength" Elo used when UCI_LimitStrength is off. The blunder budget
# floors at its tightest (~50cp) by ~2200, so this gives near-pure-engine play
# with only a thin style margin — the closest analogue to "play your best".
_FULL_STRENGTH_ELO = 3000

# Sentinel a GUI sends for an empty string option (UCI spec).
_EMPTY = "<empty>"


class _EngineLike(Protocol):
    def top_candidates(self, board: chess.Board) -> list[Candidate]: ...
    def set_movetime_ms(self, movetime_ms: int) -> None: ...
    def close(self) -> None: ...


# (in_process_scorer | None, generated_source | None, human_label)
ScorerSpec = tuple[StyleScorer | None, str | None, str]

EngineFactory = Callable[[str, int, int], _EngineLike]
ScorerFactory = Callable[[str, str | None], ScorerSpec]


@dataclass
class _Options:
    """Mutable engine configuration, populated via `setoption`."""

    prompt: str = ""
    elo: int = 1500
    limit_strength: bool = True
    stockfish_path: str = "stockfish"
    multipv: int | None = None  # None → derive from Elo via candidate_count
    movetime_ms: int = 1000
    llm_model: str | None = None
    style_weight: int = 30

    def effective_elo(self) -> int:
        return self.elo if self.limit_strength else _FULL_STRENGTH_ELO

    def effective_multipv(self) -> int:
        return self.multipv if self.multipv is not None else candidate_count(self.elo)


def _default_scorer_factory(prompt: str, model: str | None) -> ScorerSpec:
    """Build a scorer from a style prompt (real, network-backed default).

    Empty prompt → the hand-coded queen-obsessed scorer (matches the CLI's
    no-prompt default). Otherwise ask Gemini for scorer code, validate it on
    sample positions, and return the *source* for sandboxed execution. If every
    generation attempt fails validation, fall back to a neutral in-process
    scorer. Mirrors `cli._build_scorer` but is import-light and stream-agnostic
    (logging is the caller's job).
    """
    from chess_mind_ai.scorers import queen_obsessed

    if not prompt:
        return queen_obsessed, None, "queen-obsessed (hand-coded)"

    from chess_mind_ai.llm.gemini import DEFAULT_MODEL, GeminiProvider
    from chess_mind_ai.llm.prompt import SYSTEM_PROMPT, extract_code
    from chess_mind_ai.sandbox.validation import generate_and_validate
    from chess_mind_ai.scorers import neutral

    chosen_model = model or DEFAULT_MODEL
    provider = GeminiProvider(model=chosen_model)

    def _generate() -> str:
        return extract_code(provider.generate(system=SYSTEM_PROMPT, user=prompt))

    source = generate_and_validate(_generate)
    if source is not None:
        return None, source, f"prompt-driven ({chosen_model}, sandboxed)"
    return neutral, None, "neutral fallback (generation failed validation)"


class UCIEngine:
    """A UCI command processor. Feed it lines via `handle`, or run the full
    stdin/stdout loop with `run`."""

    def __init__(
        self,
        out: TextIO | None = None,
        *,
        engine_factory: EngineFactory | None = None,
        scorer_factory: ScorerFactory | None = None,
    ) -> None:
        self._out = out if out is not None else sys.stdout
        self._engine_factory: EngineFactory = engine_factory or _make_chess_engine
        self._scorer_factory: ScorerFactory = scorer_factory or _default_scorer_factory

        self._opts = _Options()
        self._board = chess.Board()

        self._engine: _EngineLike | None = None
        self._engine_dirty = True  # (re)build the Stockfish process on next need

        self._scorer: StyleScorer | None = None
        self._source: str | None = None
        self._scorer_label = "uninitialized"
        self._scorer_dirty = True  # (re)generate the scorer on next isready

    # -- output helpers ----------------------------------------------------

    def _send(self, line: str) -> None:
        self._out.write(line + "\n")
        self._out.flush()

    def _info(self, text: str) -> None:
        """Log arbitrary text to the GUI. `info string` is valid anywhere and
        GUIs render it in their engine-log pane."""
        self._send(f"info string {text}")

    # -- command dispatch --------------------------------------------------

    def run(self, stream: TextIO | None = None) -> int:
        """Read commands until EOF or `quit`. Returns a process exit code."""
        stream = stream if stream is not None else sys.stdin
        for raw in stream:
            if self.handle(raw) is False:
                break
        self._shutdown_engine()
        return 0

    def handle(self, raw: str) -> bool | None:
        """Process one command line. Returns False to terminate the loop."""
        line = raw.strip()
        if not line:
            return None
        parts = line.split()
        cmd, args = parts[0], parts[1:]

        handler = {
            "uci": self._cmd_uci,
            "isready": self._cmd_isready,
            "setoption": self._cmd_setoption,
            "ucinewgame": self._cmd_ucinewgame,
            "position": self._cmd_position,
            "go": self._cmd_go,
            "stop": lambda _a: None,  # we search synchronously; nothing to stop
            "ponderhit": lambda _a: None,
            "quit": lambda _a: False,
        }.get(cmd)

        if handler is None:
            self._info(f"unknown command: {cmd}")
            return None
        return handler(args)

    # -- individual commands ----------------------------------------------

    def _cmd_uci(self, _args: list[str]) -> None:
        self._send(f"id name {ENGINE_NAME}")
        self._send(f"id author {ENGINE_AUTHOR}")
        self._send("option name UCI_LimitStrength type check default true")
        self._send("option name UCI_Elo type spin default 1500 min 400 max 4000")
        self._send("option name Prompt type string default <empty>")
        self._send("option name Stockfish Path type string default stockfish")
        self._send("option name MultiPV type spin default 0 min 0 max 64")
        self._send("option name Move Time type spin default 1000 min 1 max 600000")
        self._send("option name LLM Model type string default <empty>")
        self._send("option name Style Weight type spin default 30 min 0 max 500")
        self._send("uciok")

    def _cmd_isready(self, _args: list[str]) -> None:
        # The GUI's configuration checkpoint: do any pending (slow) init now,
        # before the clock starts. Generate the scorer eagerly here.
        self._ensure_scorer()
        self._ensure_engine()
        self._send("readyok")

    def _cmd_setoption(self, args: list[str]) -> None:
        name, value = _parse_setoption(args)
        if name is None:
            self._info(f"malformed setoption: {' '.join(args)}")
            return
        self._apply_option(name, value)

    def _cmd_ucinewgame(self, _args: list[str]) -> None:
        self._board = chess.Board()

    def _cmd_position(self, args: list[str]) -> None:
        board = _parse_position(args)
        if board is None:
            self._info(f"malformed position: {' '.join(args)}")
            return
        self._board = board

    def _cmd_go(self, args: list[str]) -> None:
        movetime = _parse_go_movetime(args)
        self._ensure_scorer()
        self._ensure_engine()
        assert self._engine is not None
        self._engine.set_movetime_ms(movetime or self._opts.movetime_ms)

        move, breakdown = self._select(self._board)
        if move is None:
            self._send("bestmove (none)")
            return
        self._emit_info(move, breakdown)
        self._send(f"bestmove {move.uci()}")

    # -- option handling ---------------------------------------------------

    def _apply_option(self, name: str, value: str) -> None:
        key = name.lower()
        if key == "prompt":
            self._opts.prompt = "" if value == _EMPTY else value
            self._scorer_dirty = True
        elif key == "llm model":
            self._opts.llm_model = None if value in ("", _EMPTY) else value
            self._scorer_dirty = True
        elif key == "uci_elo":
            self._opts.elo = _to_int(value, self._opts.elo)
            self._engine_dirty = True  # auto-MultiPV depends on Elo
        elif key == "uci_limitstrength":
            self._opts.limit_strength = value.lower() == "true"
        elif key == "stockfish path":
            self._opts.stockfish_path = value or "stockfish"
            self._engine_dirty = True
        elif key == "multipv":
            n = _to_int(value, 0)
            self._opts.multipv = n if n > 0 else None  # 0 → auto (Elo-scaled)
            self._engine_dirty = True
        elif key == "move time":
            self._opts.movetime_ms = _to_int(value, self._opts.movetime_ms)
        elif key == "style weight":
            self._opts.style_weight = _to_int(value, self._opts.style_weight)
        else:
            self._info(f"ignoring unknown option: {name}")

    # -- lazy (re)build of engine + scorer ---------------------------------

    def _ensure_engine(self) -> None:
        if self._engine is not None and not self._engine_dirty:
            return
        self._shutdown_engine()
        try:
            self._engine = self._engine_factory(
                self._opts.stockfish_path,
                self._opts.effective_multipv(),
                self._opts.movetime_ms,
            )
            self._engine_dirty = False
        except Exception as e:  # noqa: BLE001 - report, don't crash the loop
            self._info(f"failed to start engine '{self._opts.stockfish_path}': {e}")

    def _ensure_scorer(self) -> None:
        if not self._scorer_dirty:
            return
        try:
            scorer, source, label = self._scorer_factory(
                self._opts.prompt, self._opts.llm_model
            )
            self._scorer, self._source, self._scorer_label = scorer, source, label
        except Exception as e:  # noqa: BLE001 - fall back, never crash the loop
            from chess_mind_ai.scorers import neutral

            self._scorer, self._source = neutral, None
            self._scorer_label = f"neutral fallback (scorer setup failed: {e})"
        self._scorer_dirty = False
        self._info(f"style: {self._scorer_label}")

    def _shutdown_engine(self) -> None:
        if self._engine is not None:
            try:
                self._engine.close()
            except Exception:  # noqa: BLE001
                pass
            self._engine = None

    # -- selection ---------------------------------------------------------

    def _select(
        self, board: chess.Board
    ) -> tuple[chess.Move | None, list[MoveBreakdown]]:
        if self._engine is None:
            return None, []
        elo = self._opts.effective_elo()
        weight = float(self._opts.style_weight)
        ai_color = board.turn
        if self._source is not None:
            return select_move_sandboxed(
                self._engine, self._source, board, elo, ai_color, style_weight=weight
            )
        scorer = self._scorer if self._scorer is not None else _neutral_scorer()
        return select_move(
            self._engine, scorer, board, elo, ai_color, style_weight=weight
        )

    def _emit_info(self, move: chess.Move, breakdown: list[MoveBreakdown]) -> None:
        chosen = next((b for b in breakdown if b.move == move), None)
        if chosen is None:
            return
        # `score cp` is from the side-to-move POV, matching how we store it.
        self._send(
            f"info depth 1 score cp {chosen.cp_score} pv {move.uci()} "
            f"string style={chosen.style:.2f} total={chosen.total:.2f}"
        )


# -- module-level helpers (kept simple + individually testable) -------------


def _make_chess_engine(path: str, multipv: int, movetime_ms: int) -> _EngineLike:
    return ChessEngine(path=path, multipv=multipv, movetime_ms=movetime_ms)


def _neutral_scorer() -> StyleScorer:
    from chess_mind_ai.scorers import neutral

    return neutral


def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_setoption(args: list[str]) -> tuple[str | None, str]:
    """Parse `name <name...> [value <value...>]`. Option names may contain
    spaces, so we split on the literal `value` keyword. Returns (None, "") if
    malformed."""
    if not args or args[0] != "name":
        return None, ""
    rest = args[1:]
    if "value" in rest:
        idx = rest.index("value")
        name = " ".join(rest[:idx])
        value = " ".join(rest[idx + 1:])
    else:
        name = " ".join(rest)
        value = ""
    return (name or None), value


def _parse_go_movetime(args: list[str]) -> int | None:
    """Extract `movetime N` (ms) if present. Other `go` params (wtime/btime/
    depth/nodes/infinite) are ignored in M5 (see module docstring)."""
    if "movetime" in args:
        idx = args.index("movetime")
        if idx + 1 < len(args):
            return _to_int(args[idx + 1], None) or None
    return None


def _parse_position(args: list[str]) -> chess.Board | None:
    """Parse `startpos [moves ...]` or `fen <6 fields> [moves ...]`."""
    if not args:
        return None

    if args[0] == "startpos":
        board = chess.Board()
        moves = args[2:] if len(args) > 1 and args[1] == "moves" else []
    elif args[0] == "fen":
        if len(args) < 7:
            return None
        fen = " ".join(args[1:7])
        try:
            board = chess.Board(fen)
        except ValueError:
            return None
        moves = args[8:] if len(args) > 7 and args[7] == "moves" else []
    else:
        return None

    for token in moves:
        try:
            move = chess.Move.from_uci(token)
        except (chess.InvalidMoveError, ValueError):
            return None
        if move not in board.legal_moves:
            return None
        board.push(move)
    return board


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001 - UCI takes no args
    """Entry point for the `chess-mind-ai-uci` console script."""
    return UCIEngine().run()


if __name__ == "__main__":
    sys.exit(main())
