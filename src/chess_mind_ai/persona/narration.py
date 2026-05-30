"""Ground the persona chat in the real game.

Turns the move the bot just played — plus the selector's `MoveBreakdown` (its
actual reasoning: engine cp, style score, the alternatives it passed up) — into
a structured `GameMoment` and a compact text digest fed to the chat LLM. This
is what makes the banter *true* instead of generic: the character reacts to what
genuinely happened, including why it chose a flashy move over a safer one.
"""
from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_mind_ai.selector import MoveBreakdown

# eval swings (in centipawns) below/above these are worth reacting to.
_BIG_SWING_CP = 150
# how far from "your move" a cp score counts as winning/losing.
_DECISIVE_CP = 200


@dataclass(frozen=True)
class GameMoment:
    """A snapshot of what just happened, ready to narrate."""

    color_name: str
    move_number: int
    san: str
    moving_piece: str | None
    is_capture: bool
    captured_piece: str | None
    gives_check: bool
    is_checkmate: bool
    cp_score: int
    eval_swing: int | None
    own_queen_alive: bool
    enemy_queen_alive: bool
    own_queen_in_danger: bool
    passed_up: str | None
    events: tuple[str, ...]


def describe_move(
    board_before: chess.Board,
    move: chess.Move,
    breakdown: list[MoveBreakdown],
    own_color: chess.Color,
    *,
    prev_cp: int | None = None,
) -> GameMoment:
    """Build a `GameMoment` from the position before the move, the chosen move,
    and the selector breakdown. `prev_cp` is the bot's cp score on its previous
    move (for swing detection); pass None on the first move."""
    chosen = next((b for b in breakdown if b.move == move), None)
    cp_score = chosen.cp_score if chosen is not None else 0

    moving_pt = board_before.piece_type_at(move.from_square)
    is_capture = board_before.is_capture(move)
    captured_pt = _captured_piece_type(board_before, move) if is_capture else None
    gives_check = board_before.gives_check(move)

    after = board_before.copy(stack=False)
    after.push(move)

    own_queen_sqs = list(after.pieces(chess.QUEEN, own_color))
    own_queen_alive = bool(own_queen_sqs)
    enemy_queen_alive = bool(after.pieces(chess.QUEEN, not own_color))
    own_queen_in_danger = any(
        after.is_attacked_by(not own_color, sq)
        and not after.attackers(own_color, sq)
        for sq in own_queen_sqs
    )

    eval_swing = None if prev_cp is None else cp_score - prev_cp
    passed_up = _passed_up(board_before, move, breakdown)

    events = _events(
        is_capture=is_capture,
        captured_pt=captured_pt,
        gives_check=gives_check,
        is_checkmate=after.is_checkmate(),
        moving_pt=moving_pt,
        own_queen_in_danger=own_queen_in_danger,
        own_queen_alive=own_queen_alive,
        prev_cp=prev_cp,
        cp_score=cp_score,
        eval_swing=eval_swing,
    )

    return GameMoment(
        color_name="White" if own_color == chess.WHITE else "Black",
        move_number=board_before.fullmove_number,
        san=board_before.san(move),
        moving_piece=chess.piece_name(moving_pt) if moving_pt else None,
        is_capture=is_capture,
        captured_piece=chess.piece_name(captured_pt) if captured_pt else None,
        gives_check=gives_check,
        is_checkmate=after.is_checkmate(),
        cp_score=cp_score,
        eval_swing=eval_swing,
        own_queen_alive=own_queen_alive,
        enemy_queen_alive=enemy_queen_alive,
        own_queen_in_danger=own_queen_in_danger,
        passed_up=passed_up,
        events=events,
    )


def is_dramatic(moment: GameMoment) -> bool:
    """Should the character pipe up about this move? React on real drama, not
    every quiet developing move (plan: speak on dramatic events)."""
    return bool(moment.events)


def digest(moment: GameMoment) -> str:
    """A compact [GAME UPDATE] note. Facts only; the LLM supplies the attitude."""
    lines = [
        "[GAME UPDATE]",
        f"You are {moment.color_name}. It is move {moment.move_number}.",
        f"You just played {moment.san}.",
    ]
    if moment.is_checkmate:
        lines.append("CHECKMATE — you just WON the game!")
    elif moment.gives_check:
        lines.append("It gives CHECK.")
    if moment.moving_piece:
        lines.append(f"You moved your {moment.moving_piece}.")
    if moment.is_capture and moment.captured_piece:
        lines.append(f"It CAPTURES the enemy {moment.captured_piece}.")
    lines.append(f"Engine evaluation now: {moment.cp_score:+d} cp ({_verdict(moment.cp_score)}).")
    if moment.eval_swing is not None and abs(moment.eval_swing) >= _BIG_SWING_CP:
        direction = "in your favor" if moment.eval_swing > 0 else "against you"
        lines.append(f"That was a big swing {direction} ({moment.eval_swing:+d} cp).")
    lines.append(
        f"Your queen is {'alive' if moment.own_queen_alive else 'GONE'}; "
        f"the enemy queen is {'alive' if moment.enemy_queen_alive else 'gone'}."
    )
    if moment.own_queen_in_danger:
        lines.append("WARNING: your queen is under attack and undefended!")
    if moment.passed_up:
        lines.append(
            f"Your style made you pick this over the safer {moment.passed_up}."
        )
    lines.append(
        "React in character, 1-2 short sentences. Do not narrate like a "
        "commentator; feel it."
    )
    return "\n".join(lines)


def _verdict(cp: int) -> str:
    if cp >= _DECISIVE_CP:
        return "you are winning"
    if cp <= -_DECISIVE_CP:
        return "you are losing"
    return "roughly equal"


def _captured_piece_type(board: chess.Board, move: chess.Move) -> int | None:
    if board.is_en_passant(move):
        return chess.PAWN
    pt = board.piece_type_at(move.to_square)
    return pt


def _passed_up(
    board_before: chess.Board, move: chess.Move, breakdown: list[MoveBreakdown]
) -> str | None:
    """The strongest engine alternative (within budget) the bot declined, as SAN
    with its cp — so the character can brag about choosing style over safety."""
    alts = [b for b in breakdown if b.move != move and b.allowed]
    if not alts:
        return None
    best = max(alts, key=lambda b: b.cp_score)
    return f"{board_before.san(best.move)} ({best.cp_score:+d} cp)"


def _events(
    *,
    is_capture: bool,
    captured_pt: int | None,
    gives_check: bool,
    is_checkmate: bool,
    moving_pt: int | None,
    own_queen_in_danger: bool,
    own_queen_alive: bool,
    prev_cp: int | None,
    cp_score: int,
    eval_swing: int | None,
) -> tuple[str, ...]:
    events: list[str] = []
    if is_checkmate:
        events.append("checkmate")
    if gives_check:
        events.append("check")
    if captured_pt == chess.QUEEN:
        events.append("captured_enemy_queen")
    elif is_capture:
        events.append("capture")
    if not own_queen_alive:
        events.append("own_queen_gone")
    elif own_queen_in_danger:
        events.append("own_queen_in_danger")
    if eval_swing is not None and eval_swing >= _BIG_SWING_CP:
        events.append("swing_up")
    elif eval_swing is not None and eval_swing <= -_BIG_SWING_CP:
        events.append("swing_down")
    return tuple(events)
