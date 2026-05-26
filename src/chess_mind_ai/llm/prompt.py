"""System prompt + response post-processing for scorer-code generation.

The system prompt teaches the `ReadOnlyBoard` API + the curated `chess`
namespace + the `piece(name)` helper that generated code may use. Keep it in
sync with `chess_mind_ai.readonly_board` (the `ReadOnlyBoard` surface and
`scorer_globals`) and with the AST allowlist in
`chess_mind_ai.sandbox.validator`.
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

`ctx` is a read-only view of the board (a ReadOnlyBoard); it is never mutable.
- In action_score, `ctx` is the position BEFORE `move` is played, and `move` is
  the move being judged. To inspect the position that RESULTS from the move
  (e.g. "does this leave my queen hanging?", "what does it capture?"), call
  `ctx.peek(move)`, which returns a new ReadOnlyBoard for the position after it.
- In state_score and trajectory_score, `ctx` is the position AFTER your move.

Conventions:
- Squares are ints 0..63 (a1=0, b1=1, ..., h8=63).
- Colors are booleans: white is True, black is False. Your side is
  `ctx.own_color`; the opponent is `not ctx.own_color`.
- Piece types are ints 1..6. Use the helper `piece(name)` to get one, where
  `name` is "pawn", "knight", "bishop", "rook", "queen", or "king".

Methods you may call on `ctx` (and on the result of `ctx.peek(move)`):
    ctx.own_color                       -> bool   (your side; white=True)
    ctx.turn                            -> bool   (side to move)
    ctx.fullmove_number                 -> int
    ctx.halfmove_clock                  -> int
    ctx.ply()                           -> int
    ctx.piece_type_at(square)           -> int | None
    ctx.color_at(square)                -> bool | None
    ctx.king(color)                     -> int | None   (square of that king)
    ctx.squares_with(piece_type, color) -> tuple of squares
    ctx.piece_count(piece_type, color)  -> int
    ctx.has_piece(piece_type, color)    -> bool
    ctx.attacks(square)                 -> tuple of squares that piece attacks
    ctx.attackers(color, square)        -> tuple of that color's pieces hitting square
    ctx.is_attacked_by(color, square)   -> bool
    ctx.is_check()                      -> bool
    ctx.is_checkmate()                  -> bool
    ctx.is_stalemate()                  -> bool
    ctx.is_insufficient_material()      -> bool
    ctx.legal_moves()                   -> tuple of legal moves
    ctx.is_legal(move)                  -> bool
    ctx.is_capture(move)                -> bool
    ctx.is_en_passant(move)             -> bool
    ctx.is_castling(move)               -> bool
    ctx.gives_check(move)               -> bool
    ctx.moving_piece_type(move)         -> int | None  (type of the moving piece)
    ctx.move_history()                  -> tuple of moves played so far
    ctx.own_move_count(piece_type)      -> int  (times your side moved this type)
    ctx.peek(move)                      -> ReadOnlyBoard  (position AFTER move)

A `move` has integer attributes `move.from_square` and `move.to_square`, plus
`move.promotion` (a piece-type int, or None).

The `chess` namespace provides constants and pure helpers:
    chess.WHITE, chess.BLACK
    chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING
    chess.SQUARES, chess.FILE_NAMES, chess.RANK_NAMES
    chess.square(file, rank)            -> int
    chess.square_file(square)           -> int   (0=a .. 7=h)
    chess.square_rank(square)           -> int   (0=rank1 .. 7=rank8)
    chess.square_name(square)           -> str
    chess.square_distance(a, b)         -> int   (king-move / Chebyshev distance)
    chess.square_manhattan_distance(a, b) -> int
    chess.parse_square(name)            -> int

Hard constraints (your code will be rejected by an AST validator otherwise):
- Do not import anything.
- Do not define classes, lambdas, or decorators.
- Do not use try / except / raise / with / async / await / yield / del / global / nonlocal.
- Do not call: open, eval, exec, compile, __import__, input, globals, locals,
  vars, dir, getattr, setattr, delattr, hasattr, memoryview, breakpoint, type, super.
- Do not access any attribute starting with an underscore (e.g. __class__, _board).
- Do not put '__' inside a string literal.
- Do not mutate ctx or move (they are read-only).

Allowed builtins: abs, min, max, sum, len, range, float, int, bool, round.

Return numeric scores. Use positive values for behavior matching the user's
requested style and negative values for behavior violating it. Per-component
scores should usually be in the range [-5, +5]; outputs are clamped to [-10, +10].

Worked example — a "queen-obsessed" style (move/capture/check with the queen,
keep it active near the enemy king, and don't hang or trade it):

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
