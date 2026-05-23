from __future__ import annotations

import chess

PIECE_NAMES: dict[str, chess.PieceType] = {
    "pawn": chess.PAWN,
    "knight": chess.KNIGHT,
    "bishop": chess.BISHOP,
    "rook": chess.ROOK,
    "queen": chess.QUEEN,
    "king": chess.KING,
}


def _piece_type(name: str) -> chess.PieceType:
    key = name.lower()
    if key not in PIECE_NAMES:
        raise ValueError(f"Unknown piece name: {name}")
    return PIECE_NAMES[key]


class SafeChessContext:
    """Read-only view onto a chess position + game history, exposed to style scorers.

    Methods are intentionally narrow and side-effect-free. The plan (section 7)
    describes the full long-term API; we implement the subset needed by the
    M2 hand-coded queen-obsessed scorer.
    """

    def __init__(self, board: chess.Board, own_color: chess.Color):
        # Keep the move_stack so trajectory queries can replay from the root.
        self._board = board.copy()
        self._own_color = own_color

    @property
    def own_color(self) -> chess.Color:
        return self._own_color

    def moving_piece_is(self, move: chess.Move, piece_name: str) -> bool:
        piece = self._board.piece_at(move.from_square)
        if piece is None:
            return False
        return piece.piece_type == _piece_type(piece_name)

    def is_capture(self, move: chess.Move) -> bool:
        return self._board.is_capture(move)

    def gives_check(self, move: chess.Move) -> bool:
        return self._board.gives_check(move)

    def destination_near_enemy_king(self, move: chess.Move, distance: int = 2) -> bool:
        enemy_king = self._board.king(not self._own_color)
        if enemy_king is None:
            return False
        return chess.square_distance(move.to_square, enemy_king) <= distance

    def causes_trade_of_piece(self, move: chess.Move, piece_name: str) -> bool:
        """Heuristic: the moved piece (of given type) lands on a square attacked by
        the opponent after the move. Good enough for M2 — refine later."""
        pt = _piece_type(piece_name)
        moving = self._board.piece_at(move.from_square)
        if moving is None or moving.piece_type != pt:
            return False
        after = self._board.copy(stack=False)
        after.push(move)
        return after.is_attacked_by(not self._own_color, move.to_square)

    def hangs_piece_after_move(self, move: chess.Move, piece_name: str) -> bool:
        """After the move, do we have any piece of this type attacked but not defended?"""
        pt = _piece_type(piece_name)
        after = self._board.copy(stack=False)
        after.push(move)
        own = self._own_color
        for square, piece in after.piece_map().items():
            if piece.color == own and piece.piece_type == pt:
                attackers = after.attackers(not own, square)
                defenders = after.attackers(own, square)
                if attackers and not defenders:
                    return True
        return False

    def piece_mobility(self, piece_name: str) -> float:
        """Count legal moves available to our pieces of this type from this position."""
        pt = _piece_type(piece_name)
        probe = self._board.copy(stack=False)
        probe.turn = self._own_color
        count = 0
        for mv in probe.legal_moves:
            piece = probe.piece_at(mv.from_square)
            if piece is not None and piece.piece_type == pt:
                count += 1
        return float(count)

    def piece_attack_pressure(self, piece_name: str) -> float:
        """Number of enemy-occupied squares attacked by our pieces of this type."""
        pt = _piece_type(piece_name)
        own = self._own_color
        count = 0
        for sq, piece in self._board.piece_map().items():
            if piece.color == own and piece.piece_type == pt:
                for target in self._board.attacks(sq):
                    target_piece = self._board.piece_at(target)
                    if target_piece is not None and target_piece.color != own:
                        count += 1
        return float(count)

    def piece_centralization(self, piece_name: str) -> float:
        """Average centralization across our pieces of this type. 0 = corner, 1 = center."""
        pt = _piece_type(piece_name)
        own = self._own_color
        total = 0.0
        n = 0
        for sq, piece in self._board.piece_map().items():
            if piece.color == own and piece.piece_type == pt:
                file_dist = abs(chess.square_file(sq) - 3.5)
                rank_dist = abs(chess.square_rank(sq) - 3.5)
                total += 1.0 - ((file_dist + rank_dist) / 7.0)
                n += 1
        return total / n if n > 0 else 0.0

    def piece_under_attack(self, piece_name: str) -> float:
        """Count of our pieces of this type attacked by the enemy."""
        pt = _piece_type(piece_name)
        own = self._own_color
        count = 0
        for sq, piece in self._board.piece_map().items():
            if piece.color == own and piece.piece_type == pt:
                if self._board.is_attacked_by(not own, sq):
                    count += 1
        return float(count)

    def count_own_moves_by_piece(self, piece_name: str) -> int:
        """Walk the board's move_stack; count moves by our color of this piece type.

        Replays from `board.root()` (whatever position the move_stack started
        from) rather than the standard starting position, so we work correctly
        for boards constructed from arbitrary FENs.
        """
        pt = _piece_type(piece_name)
        replay = self._board.root()
        count = 0
        for mv in self._board.move_stack:
            if replay.turn == self._own_color:
                piece = replay.piece_at(mv.from_square)
                if piece is not None and piece.piece_type == pt:
                    count += 1
            replay.push(mv)
        return count

    def own_queen_was_traded(self) -> bool:
        own = self._own_color
        return not any(
            piece.color == own and piece.piece_type == chess.QUEEN
            for piece in self._board.piece_map().values()
        )
