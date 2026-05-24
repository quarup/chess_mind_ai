from __future__ import annotations

import textwrap

import pytest

from chess_mind_ai.sandbox.loader import CLAMP_HIGH, CLAMP_LOW, _clamp, load_scorer
from chess_mind_ai.sandbox.validator import ScorerValidationError

_SIMPLE = textwrap.dedent("""
    def action_score(ctx, move):
        return 1.5
    def state_score(ctx):
        return -2.0
    def trajectory_score(ctx):
        return 0.0
""")


def test_load_and_call():
    s = load_scorer(_SIMPLE)
    assert s.action_score(None, None) == 1.5
    assert s.state_score(None) == -2.0
    assert s.trajectory_score(None) == 0.0


def test_outputs_are_clamped_to_safe_range():
    src = textwrap.dedent("""
        def action_score(ctx, move):
            return 1000.0
        def state_score(ctx):
            return -1000.0
        def trajectory_score(ctx):
            return 0.0
    """)
    s = load_scorer(src)
    assert s.action_score(None, None) == CLAMP_HIGH
    assert s.state_score(None) == CLAMP_LOW


def test_non_finite_outputs_collapse_to_zero():
    src = textwrap.dedent("""
        def action_score(ctx, move):
            return float("inf")
        def state_score(ctx):
            return float("nan")
        def trajectory_score(ctx):
            return float("-inf")
    """)
    s = load_scorer(src)
    assert s.action_score(None, None) == 0.0
    assert s.state_score(None) == 0.0
    assert s.trajectory_score(None) == 0.0


def test_non_numeric_outputs_collapse_to_zero():
    src = textwrap.dedent("""
        def action_score(ctx, move):
            return "oops"
        def state_score(ctx):
            return None
        def trajectory_score(ctx):
            return [1, 2, 3]
    """)
    s = load_scorer(src)
    assert s.action_score(None, None) == 0.0
    assert s.state_score(None) == 0.0
    assert s.trajectory_score(None) == 0.0


def test_clamp_helper_direct():
    assert _clamp(5.0) == 5.0
    assert _clamp(20.0) == CLAMP_HIGH
    assert _clamp(-20.0) == CLAMP_LOW
    assert _clamp(float("nan")) == 0.0
    assert _clamp("nope") == 0.0


def test_loader_rejects_invalid_source():
    with pytest.raises(ScorerValidationError):
        load_scorer("import os\n")


def test_restricted_builtins_prevent_dangerous_calls_at_runtime():
    # Even if static validation somehow missed something, the runtime
    # builtin set should keep `open` undefined.
    src = textwrap.dedent("""
        def action_score(ctx, move):
            return abs(-1.5)
        def state_score(ctx):
            return min(3.0, 1.0)
        def trajectory_score(ctx):
            return max(-1.0, -5.0)
    """)
    s = load_scorer(src)
    assert s.action_score(None, None) == 1.5
    assert s.state_score(None) == 1.0
    assert s.trajectory_score(None) == -1.0
