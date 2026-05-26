"""Sample-position validation: a one-time acceptance gate for a generated scorer.

Run *once* right after the LLM produces scorer code and *before* the game
starts (design doc §7 checklist, §8 step 5; plan.md §11.2). We execute the
scorer — in the same sandboxed worker the game uses — on a handful of canned
positions and reject it if it misbehaves, so we can regenerate (ask the LLM
again) or fall back to neutral engine play instead of discovering mid-game that
the scorer is broken or useless.

This is a *quality / sanity* gate, **not** a security layer. Security is still
the AST allowlist validator + the OS sandbox; here we only ask "did the LLM
produce a usable, non-degenerate scorer for this prompt?".

The per-move sandbox already fails closed (crash / timeout / escape → the
selector falls back to a neutral all-zero style for that move). But that
fallback is silent and per-move: a scorer that is syntactically valid yet
behaviorally dead (always returns the same value, so it can never prefer one
legal move over another) would pass the sandbox every move and quietly make the
bot play pure engine all game. This gate catches that up front.

Reject criteria (from the spec):
- static AST validation fails;
- the scorer crashes / times out / returns malformed output on any canned
  position (surfaces as the sandbox returning ``None``);
- the scorer is *constant* — it never assigns different style to different
  candidate moves in *any* canned position, so it cannot influence selection.

Non-numeric / non-finite / absurd outputs are already neutralized upstream by
the loader's output clamp (``[-10, +10]``, non-finite → 0.0), so they cannot
reach this gate as invalid values.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import chess

from chess_mind_ai.sandbox.validator import (
    ScorerValidationError,
    validate_generated_code,
)
from chess_mind_ai.sandbox.worker import score_candidates_sandboxed

# (label, FEN). The scorer's side is whichever color is to move in the FEN, so
# the candidate moves we score are always the scorer's own moves. Chosen to
# cover the motifs the plan calls out: opening, a queen capture, a queen under
# attack, a mate-in-one, an endgame, a pawn-only shape, and a queenside-heavy
# position.
SAMPLE_POSITIONS: tuple[tuple[str, str], ...] = (
    ("starting position", chess.STARTING_FEN),
    ("queen capture available", "4k3/8/8/8/3pP3/2B5/8/3QK3 w - - 0 1"),
    ("queen under attack", "4k3/8/8/3q4/8/8/3Q4/4K3 w - - 0 1"),
    ("checkmate threat", "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1"),
    ("king-and-pawn endgame", "8/8/8/4k3/8/4P3/4K3/8 w - - 0 1"),
    ("pawn-only", "4k3/pppppppp/8/8/8/8/PPPPPPPP/4K3 w - - 0 1"),
    ("queenside-heavy", "r3k2r/pppp4/8/8/8/8/PPPP4/R3K2R w KQkq - 0 1"),
)

# Two style sums closer than this are treated as equal when checking whether a
# scorer discriminates between candidate moves.
_DISCRIMINATION_EPS = 1e-9


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of sample-position validation. ``reason`` is empty when ``ok``."""

    ok: bool
    reason: str = ""


def validate_scorer_source(
    source: str,
    *,
    sample_positions: tuple[tuple[str, str], ...] = SAMPLE_POSITIONS,
    **sandbox_kwargs: object,
) -> ValidationResult:
    """Run ``source`` on the canned positions and judge whether it is usable.

    Returns ``ValidationResult(ok=True)`` if the scorer validates statically,
    runs cleanly on every sample position, and discriminates between candidate
    moves in at least one of them. Otherwise ``ok=False`` with a human-readable
    ``reason``. ``sandbox_kwargs`` (e.g. ``timeout_s``, ``mem_mb``) are forwarded
    to the worker so the gate uses the same limits as the game.
    """
    try:
        validate_generated_code(source)
    except ScorerValidationError as e:
        return ValidationResult(False, f"static validation failed: {e}")

    discriminated = False
    for label, fen in sample_positions:
        board = chess.Board(fen)
        candidates = list(board.legal_moves)
        if not candidates:
            continue

        triples = score_candidates_sandboxed(
            source, board, board.turn, candidates, **sandbox_kwargs
        )
        if triples is None:
            return ValidationResult(
                False,
                f"scorer crashed, timed out, or returned malformed output on "
                f"'{label}'",
            )

        styles = [a + s + t for (a, s, t) in triples]
        if len(styles) > 1 and (max(styles) - min(styles)) > _DISCRIMINATION_EPS:
            discriminated = True

    if not discriminated:
        return ValidationResult(
            False,
            "scorer is constant: it never prefers one legal move over another "
            "on any sample position, so it cannot influence move selection",
        )

    return ValidationResult(True)


def generate_and_validate(
    generate: Callable[[], str],
    *,
    max_attempts: int = 3,
    on_reject: Callable[[int, ValidationResult], None] | None = None,
    **sandbox_kwargs: object,
) -> str | None:
    """Call ``generate`` until it yields a scorer that passes validation.

    ``generate`` returns ready-to-run scorer source (already extracted from any
    LLM response). On each rejection ``on_reject(attempt, result)`` is invoked
    (e.g. to log why) before retrying. Returns the first passing source, or
    ``None`` if all ``max_attempts`` are rejected — the caller should then fall
    back to neutral engine play (plan §14).
    """
    for attempt in range(1, max_attempts + 1):
        source = generate()
        result = validate_scorer_source(source, **sandbox_kwargs)
        if result.ok:
            return source
        if on_reject is not None:
            on_reject(attempt, result)
    return None
