from __future__ import annotations

from dataclasses import dataclass

import chess
import chess.engine

MATE_CP = 100_000


@dataclass(frozen=True)
class Candidate:
    move: chess.Move
    cp_score: int


class ChessEngine:
    def __init__(self, path: str = "stockfish", multipv: int = 10, movetime_ms: int = 1000):
        self._engine = chess.engine.SimpleEngine.popen_uci(path)
        self._multipv = multipv
        self._movetime_ms = movetime_ms

    def set_movetime_ms(self, movetime_ms: int) -> None:
        """Adjust per-move think time. Used by the UCI layer to honor a
        GUI-supplied `go movetime N` for the next search (plan.md M5)."""
        self._movetime_ms = movetime_ms

    def top_candidates(self, board: chess.Board) -> list[Candidate]:
        if board.is_game_over():
            return []

        info_list = self._engine.analyse(
            board,
            chess.engine.Limit(time=self._movetime_ms / 1000),
            multipv=self._multipv,
        )

        results: list[Candidate] = []
        for info in info_list:
            pv = info.get("pv")
            if not pv:
                continue
            score = info["score"].pov(board.turn)
            cp = score.score(mate_score=MATE_CP)
            if cp is None:
                continue
            results.append(Candidate(move=pv[0], cp_score=cp))
        return results

    def close(self) -> None:
        self._engine.quit()

    def __enter__(self) -> ChessEngine:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
