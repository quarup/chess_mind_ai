"""Tests for the isolated scorer worker (M4 portable core + Linux backend).

These spawn real subprocesses; no Stockfish or network needed. The Linux
`unshare` isolation path is exercised here when available.
"""
from __future__ import annotations

import random
import sys
import textwrap
import time
from dataclasses import dataclass

import chess
import pytest

from chess_mind_ai.engine import Candidate
from chess_mind_ai.sandbox.worker import (
    _isolation_prefix,
    score_candidates_sandboxed,
)
from chess_mind_ai.scorers import queen_obsessed
from chess_mind_ai.selector import select_move, select_move_sandboxed

_QUEEN_BONUS = textwrap.dedent("""
    def action_score(ctx, move):
        return 1.0 if ctx.moving_piece_type(move) == piece("queen") else 0.0
    def state_score(ctx):
        return 0.0
    def trajectory_score(ctx):
        return 0.0
""")

# ReadOnlyBoard scorer source equivalent to the hand-coded queen_obsessed
# module. Kept inline as a parity reference: run through the sandbox (as LLM
# output would be) it should pick the same move as the in-process module scorer,
# confirming the sandboxed and in-process paths agree.
_QUEEN_OBSESSED_RO = textwrap.dedent("""
    def action_score(ctx, move):
        score = 0.0
        own = ctx.own_color
        after = ctx.peek(move)
        if ctx.moving_piece_type(move) == piece("queen"):
            score += 1.2
            if ctx.is_capture(move):
                score += 0.9
            if ctx.gives_check(move):
                score += 0.8
            enemy_king = ctx.king(not own)
            if enemy_king is not None and chess.square_distance(move.to_square, enemy_king) <= 2:
                score += 0.5
            if after.is_attacked_by(not own, move.to_square):
                score -= 2.5
        for sq in after.squares_with(piece("queen"), own):
            if after.is_attacked_by(not own, sq) and not after.attackers(own, sq):
                score -= 2.0
        return score

    def state_score(ctx):
        own = ctx.own_color
        score = 0.0
        for sq in ctx.squares_with(piece("queen"), own):
            for target in ctx.attacks(sq):
                if ctx.color_at(target) != own:
                    score += 0.1
                if ctx.color_at(target) == (not own):
                    score += 0.2
            if ctx.is_attacked_by(not own, sq):
                score -= 1.2
        return score

    def trajectory_score(ctx):
        own = ctx.own_color
        score = 0.3 * min(ctx.own_move_count(piece("queen")), 5)
        if not ctx.has_piece(piece("queen"), own):
            score -= 5.0
        return score
""")

_CONST = textwrap.dedent("""
    def action_score(ctx, move):
        return 1.0
    def state_score(ctx):
        return 2.0
    def trajectory_score(ctx):
        return 3.0
""")


@dataclass
class FakeEngine:
    candidates: list[Candidate]

    def top_candidates(self, board: chess.Board) -> list[Candidate]:  # noqa: ARG002
        return list(self.candidates)


def test_scores_candidates_correctly():
    board = chess.Board()
    board.push_san("e4")
    board.push_san("e5")  # white to move; Qh5 is a queen move
    qh5 = chess.Move.from_uci("d1h5")
    nf3 = chess.Move.from_uci("g1f3")
    triples = score_candidates_sandboxed(_QUEEN_BONUS, board, chess.WHITE, [qh5, nf3])
    assert triples == [(1.0, 0.0, 0.0), (0.0, 0.0, 0.0)]


def test_history_is_reconstructed_for_trajectory():
    # Build a board with real history and confirm the worker sees it.
    board = chess.Board()
    for san in ["e4", "e5", "Qh5", "Nc6"]:
        board.push_san(san)
    src = textwrap.dedent("""
        def action_score(ctx, move):
            return 0.0
        def state_score(ctx):
            return 0.0
        def trajectory_score(ctx):
            return float(ctx.own_move_count(piece("queen")))
    """)
    [(_, _, traj)] = score_candidates_sandboxed(
        src, board, chess.WHITE, [chess.Move.from_uci("h5f7")]
    )
    # trajectory is scored on the *after* state, so the queen has now moved
    # twice (Qh5 in the replayed history + the candidate Qxf7).
    assert traj == 2.0


def test_infinite_loop_times_out_to_none():
    src = textwrap.dedent("""
        def action_score(ctx, move):
            while True:
                pass
        def state_score(ctx):
            return 0.0
        def trajectory_score(ctx):
            return 0.0
    """)
    start = time.time()
    result = score_candidates_sandboxed(
        src, chess.Board(), chess.WHITE,
        [chess.Move.from_uci("e2e4")], timeout_s=1.5,
    )
    elapsed = time.time() - start
    assert result is None
    assert elapsed < 5.0  # killed near the timeout, not hanging


def test_memory_bomb_returns_none():
    src = textwrap.dedent("""
        def action_score(ctx, move):
            x = bytearray(3 * 1024 * 1024 * 1024)
            return float(len(x))
        def state_score(ctx):
            return 0.0
        def trajectory_score(ctx):
            return 0.0
    """)
    result = score_candidates_sandboxed(
        src, chess.Board(), chess.WHITE,
        [chess.Move.from_uci("e2e4")], mem_mb=512,
    )
    assert result is None


def test_invalid_source_returns_none():
    assert score_candidates_sandboxed(
        "import os\n", chess.Board(), chess.WHITE,
        [chess.Move.from_uci("e2e4")],
    ) is None


def test_runtime_error_in_scorer_returns_none():
    # Calls a ctx method that does not exist -> AttributeError in the worker.
    src = textwrap.dedent("""
        def action_score(ctx, move):
            return ctx.no_such_method()
        def state_score(ctx):
            return 0.0
        def trajectory_score(ctx):
            return 0.0
    """)
    assert score_candidates_sandboxed(
        src, chess.Board(), chess.WHITE, [chess.Move.from_uci("e2e4")]
    ) is None


@pytest.mark.skipif(sys.platform != "linux", reason="unshare backend is Linux-only")
def test_isolation_backend_available_and_scoring_works():
    prefix = _isolation_prefix("auto")
    if not prefix:
        pytest.skip("no unprivileged namespace support in this environment")
    assert prefix[0] == "unshare"
    # Scoring must still work through the namespace wrapper.
    triples = score_candidates_sandboxed(
        _CONST, chess.Board(), chess.WHITE,
        [chess.Move.from_uci("e2e4")], isolation="auto",
    )
    assert triples == [(1.0, 2.0, 3.0)]


def test_isolation_none_still_scores():
    triples = score_candidates_sandboxed(
        _CONST, chess.Board(), chess.WHITE,
        [chess.Move.from_uci("e2e4")], isolation="none",
    )
    assert triples == [(1.0, 2.0, 3.0)]


# --- sandboxed selector integration (no Stockfish needed) ------------------ #

_TWIN_CAPTURE_FEN = "4k3/8/8/8/3pP3/2B5/8/3QK3 w - - 0 1"
_QXD4 = chess.Move.from_uci("d1d4")
_BXD4 = chess.Move.from_uci("c3d4")


def test_sandboxed_selector_uses_generated_style():
    board = chess.Board(_TWIN_CAPTURE_FEN)
    engine = FakeEngine([Candidate(_BXD4, 100), Candidate(_QXD4, 85)])
    chosen, _ = select_move_sandboxed(
        engine, _QUEEN_BONUS, board, target_elo=1500,
        own_color=chess.WHITE, rng=random.Random(0),
    )
    assert chosen == _QXD4  # style promotes the queen capture within budget


def test_sandboxed_selector_falls_back_to_neutral_on_bad_source():
    board = chess.Board(_TWIN_CAPTURE_FEN)
    engine = FakeEngine([Candidate(_BXD4, 100), Candidate(_QXD4, 85)])
    # Invalid source -> sandbox returns None -> neutral (pure engine) -> best cp.
    chosen, breakdown = select_move_sandboxed(
        engine, "import os\n", board, target_elo=1500,
        own_color=chess.WHITE, rng=random.Random(0),
    )
    assert chosen == _BXD4
    assert all(b.style == 0.0 for b in breakdown)


def test_readonly_port_at_parity_with_inprocess_queen_obsessed():
    """The sandboxed ReadOnlyBoard scorer source picks the same move as the
    in-process queen_obsessed module — confirming the sandboxed and in-process
    paths agree on identical scoring logic."""
    board = chess.Board(_TWIN_CAPTURE_FEN)
    cands = [Candidate(_BXD4, 100), Candidate(_QXD4, 85)]

    in_process, _ = select_move(
        FakeEngine(cands), queen_obsessed, board, target_elo=1500,
        own_color=chess.WHITE, rng=random.Random(0),
    )
    sandboxed, _ = select_move_sandboxed(
        FakeEngine(cands), _QUEEN_OBSESSED_RO, board, target_elo=1500,
        own_color=chess.WHITE, rng=random.Random(0),
    )
    assert in_process == sandboxed == _QXD4


def test_readonly_port_passes_validator_and_loads():
    """The inline port is valid under the AST allowlist and loads with the
    injected `chess` / `piece` globals available."""
    from chess_mind_ai.sandbox.loader import load_scorer

    scorer = load_scorer(_QUEEN_OBSESSED_RO)
    assert callable(scorer.action_score)
    assert callable(scorer.state_score)
    assert callable(scorer.trajectory_score)
