"""Read-only board facade exposed to generated style scorers (design option C).

Background / why this exists
----------------------------
The original `SafeChessContext` exposed a small, hand-picked set of high-level
scalar queries (piece mobility, "is this a queen capture", etc.). That surface
is the bottleneck on how expressive a generated scorer can be: a prompt like
"advance your pawns aggressively" has no way to reward pawn advancement because
no method describes it. Rather than grow that list one bespoke method per
prompt, this facade exposes a *broad set of read-only chess primitives* and
lets the generated scorer compose them. See `docs/scorer-sandbox-design.md`.

Security model (read this before widening the surface)
------------------------------------------------------
This facade is **not** the security boundary. It is a live Python object, and
any live object is a gateway to the interpreter via the object graph
(``x.__class__`` -> ``__subclasses__`` -> ``__globals__``). What actually keeps
generated code contained is:

1. The AST allowlist validator (`sandbox/validator.py`), which forbids the
   *syntax* needed to walk the object graph — including any leading-underscore
   attribute, so generated code cannot reach this object's private ``_board``.
2. The OS-level sandbox (separate process + resource limits + dropped
   FS/network) that the scorer runs inside — milestone M4. This is the real
   wall, and the reason we are comfortable exposing a broad board surface.

This object is therefore deliberately read-only (no mutators, ``__setattr__``
raises) so that, in addition to the above, generated code cannot corrupt the
game state the selector is iterating over. All returned values are plain data
(ints for squares, bools, tuples) or value objects (`chess.Move`,
`chess.Piece`); we never hand back the underlying mutable board.
"""
from __future__ import annotations

from types import SimpleNamespace

import chess

_PIECE_TYPE_BY_NAME: dict[str, chess.PieceType] = {
    "pawn": chess.PAWN,
    "knight": chess.KNIGHT,
    "bishop": chess.BISHOP,
    "rook": chess.ROOK,
    "queen": chess.QUEEN,
    "king": chess.KING,
}

# Curated subset of the python-chess module surface that generated code may use.
# Constants + pure helper functions only. Deliberately excludes anything that
# does IO or spawns processes (chess.engine, chess.pgn, chess.polyglot,
# chess.syzygy, chess.svg) and the Board constructor.
CHESS = SimpleNamespace(
    WHITE=chess.WHITE,
    BLACK=chess.BLACK,
    PAWN=chess.PAWN,
    KNIGHT=chess.KNIGHT,
    BISHOP=chess.BISHOP,
    ROOK=chess.ROOK,
    QUEEN=chess.QUEEN,
    KING=chess.KING,
    SQUARES=tuple(chess.SQUARES),
    FILE_NAMES=tuple(chess.FILE_NAMES),
    RANK_NAMES=tuple(chess.RANK_NAMES),
    square=chess.square,
    square_file=chess.square_file,
    square_rank=chess.square_rank,
    square_name=chess.square_name,
    square_distance=chess.square_distance,
    square_manhattan_distance=chess.square_manhattan_distance,
    parse_square=chess.parse_square,
)


def piece_type_from_name(name: str) -> chess.PieceType:
    """Map "queen"/"pawn"/... to a python-chess piece-type int."""
    key = name.lower()
    if key not in _PIECE_TYPE_BY_NAME:
        raise ValueError(f"Unknown piece name: {name!r}")
    return _PIECE_TYPE_BY_NAME[key]


class ReadOnlyBoard:
    """Read-only view onto a chess position + history for style scorers.

    Wraps a private copy of a `chess.Board`. Exposes only read queries; there
    are no mutators and attribute assignment raises. Squares are plain ints
    (0..63, a1=0), colors are bools (white=True), piece types are ints (1..6).
    """

    __slots__ = ("_board", "_own_color")

    def __init__(self, board: chess.Board, own_color: chess.Color):
        # Keep the move_stack so trajectory queries can replay from the root.
        object.__setattr__(self, "_board", board.copy())
        object.__setattr__(self, "_own_color", own_color)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ReadOnlyBoard is read-only")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ReadOnlyBoard is read-only")

    # --- whose turn / scorer's side -------------------------------------

    @property
    def own_color(self) -> chess.Color:
        """The color the scorer is playing (white=True)."""
        return self._own_color

    @property
    def turn(self) -> chess.Color:
        """Side to move in the current position."""
        return self._board.turn

    @property
    def fullmove_number(self) -> int:
        return self._board.fullmove_number

    @property
    def halfmove_clock(self) -> int:
        return self._board.halfmove_clock

    def ply(self) -> int:
        return self._board.ply()

    def fen(self) -> str:
        return self._board.fen()

    # --- piece queries ---------------------------------------------------

    def piece_type_at(self, square: int) -> int | None:
        return self._board.piece_type_at(square)

    def color_at(self, square: int) -> chess.Color | None:
        return self._board.color_at(square)

    def piece_at(self, square: int) -> chess.Piece | None:
        return self._board.piece_at(square)

    def king(self, color: chess.Color) -> int | None:
        return self._board.king(color)

    def squares_with(self, piece_type: int, color: chess.Color) -> tuple[int, ...]:
        """All squares occupied by `color`'s pieces of `piece_type`."""
        return tuple(self._board.pieces(piece_type, color))

    def piece_count(self, piece_type: int, color: chess.Color) -> int:
        return len(self._board.pieces(piece_type, color))

    # --- attack / defence maps ------------------------------------------

    def attacks(self, square: int) -> tuple[int, ...]:
        """Squares attacked by the piece on `square` (empty if none)."""
        return tuple(self._board.attacks(square))

    def attackers(self, color: chess.Color, square: int) -> tuple[int, ...]:
        """Squares of `color`'s pieces that attack `square`."""
        return tuple(self._board.attackers(color, square))

    def is_attacked_by(self, color: chess.Color, square: int) -> bool:
        return self._board.is_attacked_by(color, square)

    # --- check / game state ---------------------------------------------

    def is_check(self) -> bool:
        return self._board.is_check()

    def is_checkmate(self) -> bool:
        return self._board.is_checkmate()

    def is_stalemate(self) -> bool:
        return self._board.is_stalemate()

    def is_insufficient_material(self) -> bool:
        return self._board.is_insufficient_material()

    # --- move queries ----------------------------------------------------

    def legal_moves(self) -> tuple[chess.Move, ...]:
        return tuple(self._board.legal_moves)

    def is_legal(self, move: chess.Move) -> bool:
        return self._board.is_legal(move)

    def is_capture(self, move: chess.Move) -> bool:
        return self._board.is_capture(move)

    def is_en_passant(self, move: chess.Move) -> bool:
        return self._board.is_en_passant(move)

    def is_castling(self, move: chess.Move) -> bool:
        return self._board.is_castling(move)

    def gives_check(self, move: chess.Move) -> bool:
        return self._board.gives_check(move)

    def moving_piece_type(self, move: chess.Move) -> int | None:
        return self._board.piece_type_at(move.from_square)

    def peek(self, move: chess.Move) -> ReadOnlyBoard:
        """Read-only view of the position AFTER `move` is played.

        Applies `move` to a private copy and returns a fresh `ReadOnlyBoard`
        with the same `own_color`. The current board is never mutated, so
        generated `action_score(ctx, move)` code can inspect the resulting
        position (e.g. whether a piece is left hanging, or what a move
        captures) without ever being handed a mutable board.
        """
        after = self._board.copy()
        after.push(move)
        return ReadOnlyBoard(after, self._own_color)

    # --- history (for trajectory scoring) -------------------------------

    def move_history(self) -> tuple[chess.Move, ...]:
        """The moves played to reach this position, from the board root."""
        return tuple(self._board.move_stack)

    def own_move_count(self, piece_type: int) -> int:
        """How many times the scorer's side has moved a piece of this type.

        Replays from `board.root()` so this is correct for boards built from
        an arbitrary starting FEN, not just the standard initial position.
        """
        replay = self._board.root()
        count = 0
        for mv in self._board.move_stack:
            if replay.turn == self._own_color:
                piece = replay.piece_at(mv.from_square)
                if piece is not None and piece.piece_type == piece_type:
                    count += 1
            replay.push(mv)
        return count

    def has_piece(self, piece_type: int, color: chess.Color) -> bool:
        return bool(self._board.pieces(piece_type, color))


def scorer_globals(board: ReadOnlyBoard | None = None) -> dict[str, object]:
    """Build the read-only global namespace injected into generated scorers.

    Exposes the curated `chess` namespace (constants + pure helpers) plus the
    `piece` helper for name->type. The board itself is passed per-call as the
    `ctx` argument, not via globals.
    """
    return {
        "chess": CHESS,
        "piece": piece_type_from_name,
    }
