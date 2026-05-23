"""Integration tests that exercise the real Stockfish engine.

Skipped automatically when `stockfish` is not on PATH so the test suite stays
runnable on machines without it.
"""
from __future__ import annotations

import shutil

import chess
import pytest

from chess_mind_ai.engine import ChessEngine
from chess_mind_ai.scorers import queen_obsessed
from chess_mind_ai.selector import select_move

pytestmark = pytest.mark.skipif(
    shutil.which("stockfish") is None,
    reason="stockfish binary not on PATH",
)


def test_top_candidates_returns_results_for_starting_position():
    with ChessEngine(multipv=5, movetime_ms=100) as engine:
        candidates = engine.top_candidates(chess.Board())
    assert 1 <= len(candidates) <= 5
    assert all(c.move in chess.Board().legal_moves for c in candidates)


def test_short_self_play_finishes_without_crashing():
    """Play a self-game (~25 plies) with very short think time, just to make sure
    nothing blows up across many positions."""
    board = chess.Board()
    max_plies = 25

    with ChessEngine(multipv=5, movetime_ms=50) as engine:
        for _ in range(max_plies):
            if board.is_game_over():
                break
            own = board.turn
            move, _ = select_move(
                engine, queen_obsessed, board, target_elo=1500, own_color=own,
            )
            assert move is not None
            assert move in board.legal_moves
            board.push(move)
