"""System prompt + response post-processing for scorer-code generation.

The system prompt enumerates the exact subset of `SafeChessContext` the
generated code is allowed to call. Keep it in sync with
`chess_mind_ai.context.SafeChessContext`.
"""
from __future__ import annotations

import re

SYSTEM_PROMPT = """\
You generate Python scoring code for a chess style engine.

Output ONLY valid Python code. No prose, no explanations, no markdown fences.

The code MUST define exactly these three top-level functions, and nothing else:

    def action_score(ctx, move) -> float: ...
    def state_score(ctx) -> float: ...
    def trajectory_score(ctx) -> float: ...

Hard constraints (your code will be rejected by an AST validator otherwise):
- Do not import anything.
- Do not define classes, lambdas, or decorators.
- Do not use try / except / raise / with / async / await / yield / del / global / nonlocal.
- Do not call: open, eval, exec, compile, __import__, input, globals, locals,
  vars, dir, getattr, setattr, delattr, hasattr, memoryview, breakpoint.
- Do not access any dunder attribute (__class__, __dict__, __globals__, etc.).
- Do not mutate ctx or move.

Allowed builtins: abs, min, max, sum, len, range, float, int, bool, round.

You MUST call only the following methods on `ctx` (no others exist):
    ctx.moving_piece_is(move, piece_name: str) -> bool
    ctx.is_capture(move) -> bool
    ctx.gives_check(move) -> bool
    ctx.destination_near_enemy_king(move, distance: int = 2) -> bool
    ctx.causes_trade_of_piece(move, piece_name: str) -> bool
    ctx.hangs_piece_after_move(move, piece_name: str) -> bool
    ctx.piece_mobility(piece_name: str) -> float
    ctx.piece_attack_pressure(piece_name: str) -> float
    ctx.piece_centralization(piece_name: str) -> float
    ctx.piece_under_attack(piece_name: str) -> float
    ctx.count_own_moves_by_piece(piece_name: str) -> int
    ctx.own_queen_was_traded() -> bool

`piece_name` is one of: "pawn", "knight", "bishop", "rook", "queen", "king".

Return numeric scores. Use positive values for behavior matching the user's
requested style and negative values for behavior violating it. Per-component
scores should usually be in the range [-5, +5]; outputs will be clamped to
[-10, +10].
"""


_FENCE_RE = re.compile(
    r"^\s*```(?:python|py)?\s*\n(?P<body>.*?)\n```\s*$",
    re.DOTALL,
)


def extract_code(response_text: str) -> str:
    """Strip a single ```python ... ``` fence if present, otherwise return as-is.

    Models will sometimes wrap code in markdown fences despite instructions
    not to. Tolerating one outer fence is cheap and doesn't compromise safety
    (the AST validator runs on the result either way).
    """
    if response_text is None:
        raise ValueError("LLM returned no response text")
    match = _FENCE_RE.match(response_text)
    if match:
        return match.group("body")
    return response_text.strip()
