"""Compile + execute validated scorer code with restricted builtins.

Returned objects conform to `selector.StyleScorer` (three callables:
action_score, state_score, trajectory_score). All numeric outputs are
clamped to [-10, +10] and non-finite values collapse to 0.0, per plan.md
section 8 — generated scorers must never fully override the engine's
centipawn evaluation.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from chess_mind_ai.readonly_board import scorer_globals
from chess_mind_ai.sandbox.validator import (
    REQUIRED_FUNCTION_NAMES,
    ScorerValidationError,
    validate_generated_code,
)

_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "range": range,
    "float": float,
    "int": int,
    "bool": bool,
    "round": round,
    "True": True,
    "False": False,
    "None": None,
}

CLAMP_LOW = -10.0
CLAMP_HIGH = 10.0


def _clamp(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    if v < CLAMP_LOW:
        return CLAMP_LOW
    if v > CLAMP_HIGH:
        return CLAMP_HIGH
    return v


def _wrap_clamped(fn: Callable[..., Any]) -> Callable[..., float]:
    def wrapper(*args: Any, **kwargs: Any) -> float:
        return _clamp(fn(*args, **kwargs))
    return wrapper


@dataclass(frozen=True)
class GeneratedScorer:
    """Bundle of three clamped scoring callables loaded from generated code.

    Duck-types to `selector.StyleScorer`.
    """
    action_score: Callable[..., float]
    state_score: Callable[..., float]
    trajectory_score: Callable[..., float]
    source: str


def load_scorer(source: str) -> GeneratedScorer:
    """Validate, compile, and load generated scorer code.

    Raises `ScorerValidationError` if the AST validator rejects the source.
    """
    tree = validate_generated_code(source)
    code = compile(tree, filename="<generated_scorer>", mode="exec")

    # Inject the curated `chess` namespace + `piece` helper alongside the safe
    # builtins so generated scorers can call chess.* and piece("queen"). The
    # ReadOnlyBoard itself is passed per-call as the `ctx` argument, not here.
    namespace: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS, **scorer_globals()}
    exec(code, namespace, namespace)  # noqa: S102 — restricted by AST + builtins

    callables: dict[str, Callable[..., Any]] = {}
    for name in REQUIRED_FUNCTION_NAMES:
        fn = namespace.get(name)
        if not callable(fn):
            raise ScorerValidationError(
                f"Generated code did not define a callable {name!r}"
            )
        callables[name] = _wrap_clamped(fn)

    return GeneratedScorer(
        action_score=callables["action_score"],
        state_score=callables["state_score"],
        trajectory_score=callables["trajectory_score"],
        source=source,
    )
