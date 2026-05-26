"""Selector tests with a fake engine so we don't need Stockfish here."""
from __future__ import annotations

import random
from dataclasses import dataclass

import chess

from chess_mind_ai.engine import Candidate
from chess_mind_ai.scorers import neutral, queen_obsessed
from chess_mind_ai.selector import select_move


@dataclass
class FakeEngine:
    candidates: list[Candidate]

    def top_candidates(self, board: chess.Board) -> list[Candidate]:  # noqa: ARG002
        return list(self.candidates)


# A clean position where the queen and bishop can both capture the same
# undefended pawn — and the queen's destination is NOT attacked by anything,
# so no spurious "trade" penalty kicks in. Lets us isolate the action-score
# preference for the queen capture.
#
#   White: Ke1, Qd1, Bc3, Pe4    Black: Ke8, Pd4 (target)
_TWIN_CAPTURE_FEN = "4k3/8/8/8/3pP3/2B5/8/3QK3 w - - 0 1"
_QXD4 = chess.Move.from_uci("d1d4")
_BXD4 = chess.Move.from_uci("c3d4")


def test_selector_picks_queen_capture_when_engine_gap_small():
    """Style should overcome a small engine deficit at moderate Elo."""
    board = chess.Board(_TWIN_CAPTURE_FEN)
    engine = FakeEngine([
        Candidate(_BXD4, 100),
        Candidate(_QXD4, 85),  # 15cp worse, within 1500-Elo budget (~218cp)
    ])

    chosen, _ = select_move(
        engine, queen_obsessed, board, target_elo=1500,
        own_color=chess.WHITE, rng=random.Random(0),
    )
    assert chosen == _QXD4


def test_selector_respects_high_elo_budget():
    """At 2200 Elo the budget is ~50cp, so a 100cp-worse queen move gets filtered."""
    board = chess.Board(_TWIN_CAPTURE_FEN)
    engine = FakeEngine([
        Candidate(_BXD4, 100),
        Candidate(_QXD4, 0),  # 100cp worse — out of budget
    ])

    chosen, breakdown = select_move(
        engine, queen_obsessed, board, target_elo=2200,
        own_color=chess.WHITE, rng=random.Random(0),
    )
    assert chosen == _BXD4
    queen_bd = next(b for b in breakdown if b.move == _QXD4)
    assert not queen_bd.allowed


def test_neutral_scorer_plays_pure_engine():
    """The neutral fallback scorer adds zero style, so the highest-cp move wins."""
    board = chess.Board(_TWIN_CAPTURE_FEN)
    engine = FakeEngine([Candidate(_BXD4, 100), Candidate(_QXD4, 85)])
    chosen, breakdown = select_move(
        engine, neutral, board, target_elo=1500,
        own_color=chess.WHITE, rng=random.Random(0),
    )
    assert chosen == _BXD4
    assert all(b.style == 0.0 for b in breakdown)


def test_selector_returns_none_when_no_candidates():
    chosen, breakdown = select_move(
        FakeEngine([]), queen_obsessed, chess.Board(), 1500, chess.WHITE,
        rng=random.Random(0),
    )
    assert chosen is None
    assert breakdown == []


def test_selector_falls_back_when_pool_empty():
    """Single candidate is always within budget of itself; we still get a move."""
    e4 = chess.Move.from_uci("e2e4")
    chosen, _ = select_move(
        FakeEngine([Candidate(e4, 0)]), queen_obsessed, chess.Board(),
        2200, chess.WHITE, rng=random.Random(0),
    )
    assert chosen == e4
