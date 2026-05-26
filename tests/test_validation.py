"""Tests for sample-position validation (design doc §8 step 5).

These spawn the real sandbox worker (no Stockfish or Gemini needed). The
orchestration tests use a single sample position to stay fast.
"""
from __future__ import annotations

import textwrap

from chess_mind_ai.sandbox.validation import (
    SAMPLE_POSITIONS,
    ValidationResult,
    generate_and_validate,
    validate_scorer_source,
)

# Rewards queen moves -> discriminates between candidates wherever the queen can
# move (e.g. the "queen capture available" position), so it passes the gate.
_QUEEN_BONUS = textwrap.dedent("""
    def action_score(ctx, move):
        return 1.0 if ctx.moving_piece_type(move) == piece("queen") else 0.0
    def state_score(ctx):
        return 0.0
    def trajectory_score(ctx):
        return 0.0
""")

# Same value for every move in every position -> cannot influence selection.
_CONSTANT = textwrap.dedent("""
    def action_score(ctx, move):
        return 1.0
    def state_score(ctx):
        return 2.0
    def trajectory_score(ctx):
        return 3.0
""")

# Calls a method that doesn't exist -> AttributeError in the worker.
_CRASHES = textwrap.dedent("""
    def action_score(ctx, move):
        return ctx.no_such_method()
    def state_score(ctx):
        return 0.0
    def trajectory_score(ctx):
        return 0.0
""")

# A single position where a queen move exists, for fast orchestration tests.
_ONE_POS = (("queen capture available", "4k3/8/8/8/3pP3/2B5/8/3QK3 w - - 0 1"),)


def test_valid_discriminating_scorer_passes():
    result = validate_scorer_source(_QUEEN_BONUS)
    assert result.ok
    assert result.reason == ""


def test_constant_scorer_rejected():
    result = validate_scorer_source(_CONSTANT)
    assert not result.ok
    assert "constant" in result.reason


def test_statically_invalid_source_rejected():
    result = validate_scorer_source("import os\n")
    assert not result.ok
    assert "static validation" in result.reason


def test_crashing_scorer_rejected():
    result = validate_scorer_source(_CRASHES)
    assert not result.ok
    # The first sample position is the starting position.
    assert "starting position" in result.reason


def test_sample_positions_are_legal_with_moves():
    import chess

    for label, fen in SAMPLE_POSITIONS:
        board = chess.Board(fen)
        assert board.is_valid(), label
        assert board.legal_moves.count() > 0, label


def test_generate_and_validate_returns_first_passing():
    sources = iter([_CONSTANT, _QUEEN_BONUS])
    rejects: list[tuple[int, ValidationResult]] = []

    chosen = generate_and_validate(
        lambda: next(sources),
        on_reject=lambda attempt, result: rejects.append((attempt, result)),
        sample_positions=_ONE_POS,
    )
    assert chosen == _QUEEN_BONUS
    assert [a for a, _ in rejects] == [1]  # rejected once, then accepted


def test_generate_and_validate_gives_up_after_max_attempts():
    attempts: list[int] = []
    chosen = generate_and_validate(
        lambda: _CONSTANT,
        max_attempts=2,
        on_reject=lambda attempt, result: attempts.append(attempt),
        sample_positions=_ONE_POS,
    )
    assert chosen is None
    assert attempts == [1, 2]
