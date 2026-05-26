"""Neutral scorer: zero style on everything → pure engine play.

Used as the in-process fallback when prompt-driven scorer generation fails the
sample-position gate after every retry (plan §14, "always have a neutral
fallback"). Duck-types to `selector.StyleScorer`.
"""
from __future__ import annotations

import chess


def action_score(ctx: object, move: chess.Move) -> float:  # noqa: ARG001
    return 0.0


def state_score(ctx: object) -> float:  # noqa: ARG001
    return 0.0


def trajectory_score(ctx: object) -> float:  # noqa: ARG001
    return 0.0
