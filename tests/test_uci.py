"""UCI protocol-loop tests.

We drive `UCIEngine` with fake factories so nothing here needs Stockfish or the
network: a `FakeEngine` returns canned candidates and a fake scorer_factory
returns the in-process neutral scorer. That lets us exercise the real selection
path (`select_move`) deterministically and assert on the exact UCI output.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import chess

from chess_mind_ai.engine import Candidate
from chess_mind_ai.scorers import neutral, queen_obsessed
from chess_mind_ai.uci import (
    UCIEngine,
    _parse_go_movetime,
    _parse_position,
    _parse_setoption,
)


@dataclass
class FakeEngine:
    """Stand-in for ChessEngine: records construction args + movetime calls and
    returns the same top candidate (the engine's best legal move) every time."""

    path: str
    multipv: int
    movetime_ms: int
    movetime_calls: list[int] = field(default_factory=list)
    closed: bool = False

    def top_candidates(self, board: chess.Board) -> list[Candidate]:
        moves = list(board.legal_moves)
        if not moves:
            return []
        # Rank by UCI string just for determinism; cp gap is tiny so the neutral
        # scorer always yields the top one.
        moves.sort(key=lambda m: m.uci())
        return [Candidate(m, 100 - i) for i, m in enumerate(moves)]

    def set_movetime_ms(self, movetime_ms: int) -> None:
        self.movetime_ms = movetime_ms
        self.movetime_calls.append(movetime_ms)

    def close(self) -> None:
        self.closed = True


def _make_engine(harness):
    def factory(path, multipv, movetime_ms):
        eng = FakeEngine(path, multipv, movetime_ms)
        harness.append(eng)
        return eng

    return factory


def _neutral_factory(prompt, model):
    return neutral, None, "neutral (test)"


def _drive(commands, *, engine_factory=None, scorer_factory=_neutral_factory):
    out = io.StringIO()
    engines: list[FakeEngine] = []
    eng = UCIEngine(
        out=out,
        engine_factory=engine_factory or _make_engine(engines),
        scorer_factory=scorer_factory,
    )
    for c in commands:
        eng.handle(c)
    return out.getvalue(), eng, engines


# -- handshake --------------------------------------------------------------


def test_uci_handshake_lists_options_and_uciok():
    out, _, _ = _drive(["uci"])
    assert "id name ChessMind AI" in out
    assert "id author" in out
    assert out.strip().endswith("uciok")
    for opt in ("UCI_LimitStrength", "UCI_Elo", "Prompt", "Stockfish Path",
                "MultiPV", "Move Time", "LLM Model", "Style Weight"):
        assert f"option name {opt} " in out


def test_isready_returns_readyok():
    out, _, _ = _drive(["isready"])
    assert "readyok" in out


def test_quit_terminates_loop():
    eng = UCIEngine(out=io.StringIO(), scorer_factory=_neutral_factory,
                    engine_factory=_make_engine([]))
    assert eng.handle("quit") is False


# -- option parsing ---------------------------------------------------------


def test_setoption_with_multiword_value():
    name, value = _parse_setoption(
        "name Prompt value play very aggressively".split()
    )
    assert name == "Prompt"
    assert value == "play very aggressively"


def test_setoption_without_value():
    name, value = _parse_setoption("name UCI_LimitStrength".split())
    assert name == "UCI_LimitStrength"
    assert value == ""


def test_setoption_malformed_returns_none():
    name, _ = _parse_setoption("Prompt value foo".split())
    assert name is None


def test_prompt_option_marks_scorer_dirty_and_regenerates():
    seen: list[str] = []

    def factory(prompt, model):
        seen.append(prompt)
        return neutral, None, "neutral (test)"

    out = io.StringIO()
    eng = UCIEngine(out=out, scorer_factory=factory,
                    engine_factory=_make_engine([]))
    eng.handle("isready")  # first generation (empty prompt)
    eng.handle("setoption name Prompt value queen maniac")
    eng.handle("isready")  # regeneration after prompt change
    assert seen == ["", "queen maniac"]


def test_empty_sentinel_prompt_is_treated_as_empty():
    seen: list[str] = []

    def factory(prompt, model):
        seen.append(prompt)
        return neutral, None, "x"

    eng = UCIEngine(out=io.StringIO(), scorer_factory=factory,
                    engine_factory=_make_engine([]))
    eng.handle("setoption name Prompt value <empty>")
    eng.handle("isready")
    assert seen == [""]


def test_uci_elo_and_limitstrength_apply():
    eng = UCIEngine(out=io.StringIO(), scorer_factory=_neutral_factory,
                    engine_factory=_make_engine([]))
    eng.handle("setoption name UCI_Elo value 1800")
    eng.handle("setoption name UCI_LimitStrength value false")
    assert eng._opts.elo == 1800
    assert eng._opts.limit_strength is False
    # LimitStrength off → effective Elo is the full-strength sentinel, not 1800.
    assert eng._opts.effective_elo() > 1800


def test_multipv_zero_means_auto():
    eng = UCIEngine(out=io.StringIO(), scorer_factory=_neutral_factory,
                    engine_factory=_make_engine([]))
    eng.handle("setoption name MultiPV value 0")
    assert eng._opts.multipv is None
    eng.handle("setoption name MultiPV value 12")
    assert eng._opts.multipv == 12


# -- position parsing -------------------------------------------------------


def test_parse_position_startpos():
    board = _parse_position(["startpos"])
    assert board == chess.Board()


def test_parse_position_startpos_with_moves():
    board = _parse_position("startpos moves e2e4 e7e5".split())
    assert board.fen() == chess.Board(
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    ).fen()


def test_parse_position_fen_with_moves():
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    board = _parse_position(f"fen {fen} moves e2e4".split())
    assert board is not None
    assert chess.Move.from_uci("e2e4") in board.move_stack


def test_parse_position_rejects_illegal_move():
    assert _parse_position("startpos moves e2e5".split()) is None


def test_parse_position_rejects_short_fen():
    assert _parse_position("fen 8/8/8 w".split()) is None


# -- go / move timing -------------------------------------------------------


def test_parse_go_movetime():
    assert _parse_go_movetime("wtime 300000 btime 300000 movetime 500".split()) == 500
    assert _parse_go_movetime("wtime 300000 btime 300000".split()) is None


def test_go_emits_legal_bestmove_from_startpos():
    out, _, engines = _drive([
        "isready",
        "position startpos",
        "go",
    ])
    assert "bestmove" in out
    bestmove = _last_bestmove(out)
    assert bestmove not in ("(none)", None)
    # It must be a legal move from the start position.
    assert chess.Move.from_uci(bestmove) in chess.Board().legal_moves


def test_go_honors_explicit_movetime():
    out, _, engines = _drive([
        "isready",
        "position startpos",
        "go movetime 250",
    ])
    assert engines, "engine should have been built"
    assert engines[-1].movetime_calls[-1] == 250


def test_go_falls_back_to_option_movetime():
    out, eng, engines = _drive([
        "setoption name Move Time value 750",
        "isready",
        "position startpos",
        "go",
    ])
    assert engines[-1].movetime_calls[-1] == 750


def test_go_on_checkmate_returns_none():
    # Fool's mate: White is checkmated, Black to move has plenty, but set it so
    # the side to move has no moves. Use a stalemate/checkmate FEN.
    mated = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    out, _, _ = _drive([
        "isready",
        f"position fen {mated}",
        "go",
    ])
    assert _last_bestmove(out) == "(none)"


def test_go_emits_info_with_score():
    out, _, _ = _drive(["isready", "position startpos", "go"])
    info_lines = [ln for ln in out.splitlines() if ln.startswith("info depth")]
    assert info_lines
    assert "score cp" in info_lines[-1]


# -- lifecycle --------------------------------------------------------------


def test_engine_rebuilt_when_stockfish_path_changes():
    engines: list[FakeEngine] = []
    out = io.StringIO()
    eng = UCIEngine(out=out, scorer_factory=_neutral_factory,
                    engine_factory=_make_engine(engines))
    eng.handle("isready")
    assert len(engines) == 1
    eng.handle("setoption name Stockfish Path value /usr/bin/stockfish")
    eng.handle("isready")
    assert len(engines) == 2
    assert engines[0].closed  # old one was shut down
    assert engines[1].path == "/usr/bin/stockfish"


def test_run_loop_processes_until_quit_and_closes_engine():
    engines: list[FakeEngine] = []
    out = io.StringIO()
    eng = UCIEngine(out=out, scorer_factory=_neutral_factory,
                    engine_factory=_make_engine(engines))
    script = "uci\nisready\nposition startpos\ngo\nquit\nignored-after-quit\n"
    rc = eng.run(io.StringIO(script))
    assert rc == 0
    assert "uciok" in out.getvalue()
    assert "bestmove" in out.getvalue()
    assert engines[-1].closed


def test_scorer_factory_failure_falls_back_to_neutral():
    def boom(prompt, model):
        raise RuntimeError("no API key")

    out = io.StringIO()
    eng = UCIEngine(out=out, scorer_factory=boom, engine_factory=_make_engine([]))
    eng.handle("setoption name Prompt value something")
    eng.handle("isready")
    # Still ready, with a neutral fallback and an info-string explanation.
    assert "readyok" in out.getvalue()
    assert eng._scorer is neutral
    assert "fallback" in out.getvalue().lower()


def test_unknown_command_is_reported_not_fatal():
    out, _, _ = _drive(["frobnicate the bishop"])
    assert "unknown command" in out.lower()


def test_default_factory_empty_prompt_is_queen_obsessed():
    # The real default scorer factory should map an empty prompt to the
    # hand-coded queen-obsessed scorer (matching the CLI), no network needed.
    from chess_mind_ai.uci import _default_scorer_factory

    scorer, source, label = _default_scorer_factory("", None)
    assert scorer is queen_obsessed
    assert source is None
    assert "queen" in label.lower()


def _last_bestmove(out: str) -> str | None:
    for line in reversed(out.splitlines()):
        if line.startswith("bestmove "):
            return line.split(maxsplit=1)[1]
    return None
