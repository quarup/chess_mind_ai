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


@pytest.mark.parametrize("snippet,reason", [
    (_VALID_SCORER.replace("score = 0.0", "with open('x'): score = 0.0"), "With"),
    (_VALID_SCORER.replace("return score", "return (n := 1)"), "NamedExpr"),
    (_VALID_SCORER.replace('"queen"', 'f"{ctx}"'), "JoinedStr"),
    (_VALID_SCORER.replace("score = 0.0", "global score"), "Global"),
    (_VALID_SCORER.replace("score = 0.0", "del move"), "Delete"),
])
def test_unknown_constructs_fail_closed(snippet: str, reason: str):
    # The allowlist must reject anything not explicitly permitted, even
    # constructs we never thought to enumerate in a denylist.
    with pytest.raises(ScorerValidationError) as exc:
        validate_generated_code(snippet)
    assert reason in str(exc.value)


def test_try_except_fails_closed():
    snippet = textwrap.dedent("""
        def action_score(ctx, move):
            try:
                return 1.0
            except Exception:
                return 0.0
        def state_score(ctx):
            return 0.0
        def trajectory_score(ctx):
            return 0.0
    """)
    with pytest.raises(ScorerValidationError, match="Try"):
        validate_generated_code(snippet)


def test_string_literal_with_dunder_rejected():
    # Closes the `"{0.__class__.__globals__}".format(obj)` escape: dunders
    # hidden inside a string literal have no ast.Attribute node to catch.
    sneaky = _VALID_SCORER.replace(
        "score = 0.0",
        "score = len('{0.__class__.__init__.__globals__}')",
    )
    with pytest.raises(ScorerValidationError, match="dunder-escape guard"):
        validate_generated_code(sneaky)


def test_str_format_method_rejected():
    sneaky = _VALID_SCORER.replace("score = 0.0", "score = len('x'.format())")
    with pytest.raises(ScorerValidationError, match="format"):
        validate_generated_code(sneaky)


def test_private_attribute_access_rejected():
    # A read-only board facade keeps its mutable board in `_board`; generated
    # code must not be able to reach it (single leading underscore).
    sneaky = _VALID_SCORER.replace("score = 0.0", "score = ctx._board")
    with pytest.raises(ScorerValidationError, match="_board"):
        validate_generated_code(sneaky)


def test_richer_scorer_passes():
    # Option-C scorers compose primitives with loops/comprehensions/subscripts;
    # the allowlist must not be so tight that legitimate logic is rejected.
    richer = textwrap.dedent("""
        def action_score(ctx, move):
            files = ["a", "b", "c"]
            total = 0.0
            for f in files:
                if ctx.moving_piece_is(move, "queen"):
                    total += 1.0
            bonus = sum(1 for f in files if f in {"a", "b"})
            weights = {"q": 2.0, "p": 0.5}
            return total + weights["q"] + bonus

        def state_score(ctx):
            scores = [ctx.piece_mobility("queen"), ctx.piece_centralization("queen")]
            return max(scores) if scores else 0.0

        def trajectory_score(ctx):
            n = ctx.count_own_moves_by_piece("queen")
            return min(n, 5) * 0.3 if n > 0 else 0.0
    """)
    validate_generated_code(richer)  # no exception


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
