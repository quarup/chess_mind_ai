from __future__ import annotations

import textwrap

import pytest

from chess_mind_ai.sandbox.validator import (
    ScorerValidationError,
    validate_generated_code,
)

_VALID_SCORER = textwrap.dedent("""
    def action_score(ctx, move):
        score = 0.0
        if ctx.moving_piece_is(move, "queen"):
            score += 1.0
        return score

    def state_score(ctx):
        return ctx.piece_mobility("queen") * 0.5

    def trajectory_score(ctx):
        return min(ctx.count_own_moves_by_piece("queen"), 5) * 0.3
""")


def test_valid_scorer_passes():
    validate_generated_code(_VALID_SCORER)  # no exception


@pytest.mark.parametrize("snippet,reason", [
    ("import os\n" + _VALID_SCORER, "Import"),
    ("from os import path\n" + _VALID_SCORER, "ImportFrom"),
    (_VALID_SCORER + "\nfoo = lambda x: x\n", "Lambda"),
    (_VALID_SCORER + "\nclass Foo: pass\n", "ClassDef"),
    (_VALID_SCORER.replace("score = 0.0", "score = eval('1')"), "eval"),
    (_VALID_SCORER.replace("score = 0.0", "score = open('x').read()"), "open"),
    (_VALID_SCORER.replace("score = 0.0", "score = ctx.__class__"), "__class__"),
    (_VALID_SCORER.replace("score = 0.0", "score = getattr(ctx, 'foo')"), "getattr"),
])
def test_banned_constructs_rejected(snippet: str, reason: str):
    with pytest.raises(ScorerValidationError) as exc:
        validate_generated_code(snippet)
    assert reason in str(exc.value)


def test_missing_required_function_rejected():
    only_two = textwrap.dedent("""
        def action_score(ctx, move):
            return 0.0
        def state_score(ctx):
            return 0.0
    """)
    with pytest.raises(ScorerValidationError, match="trajectory_score"):
        validate_generated_code(only_two)


def test_unexpected_top_level_function_rejected():
    extra = _VALID_SCORER + textwrap.dedent("""
        def helper(x):
            return x * 2
    """)
    with pytest.raises(ScorerValidationError, match="helper"):
        validate_generated_code(extra)


def test_syntax_error_rejected():
    with pytest.raises(ScorerValidationError, match="not valid Python"):
        validate_generated_code("def action_score(ctx, move)\n    return 0")


def test_dunder_attribute_access_rejected():
    sneaky = _VALID_SCORER.replace(
        "score = 0.0",
        "score = ctx.__init_subclass__()",
    )
    with pytest.raises(ScorerValidationError, match="__init_subclass__"):
        validate_generated_code(sneaky)


def test_bare_name_reference_to_banned_builtin_rejected():
    # `f = open` would let the caller bypass the visit_Call check.
    sneaky = textwrap.dedent("""
        def action_score(ctx, move):
            f = open
            return 0.0
        def state_score(ctx):
            return 0.0
        def trajectory_score(ctx):
            return 0.0
    """)
    with pytest.raises(ScorerValidationError, match="open"):
        validate_generated_code(sneaky)


def test_decorators_rejected():
    snippet = textwrap.dedent("""
        def deco(f):
            return f

        @deco
        def action_score(ctx, move):
            return 0.0

        def state_score(ctx):
            return 0.0

        def trajectory_score(ctx):
            return 0.0
    """)
    with pytest.raises(ScorerValidationError, match="Decorator"):
        validate_generated_code(snippet)
