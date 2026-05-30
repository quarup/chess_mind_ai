from __future__ import annotations

import chess

from chess_mind_ai.llm.protocol import ChatMessage
from chess_mind_ai.persona.chat import PersonaChat, build_system_prompt
from chess_mind_ai.persona.spec import Persona
from chess_mind_ai.selector import MoveBreakdown


class FakeChatLLM:
    """Records the system prompt + history it was called with and echoes a
    canned reply."""

    def __init__(self, reply: str = "Ha!"):
        self.reply = reply
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def chat(self, system, messages, *, max_output_tokens=512, temperature=0.9):
        self.calls.append((system, list(messages)))
        return self.reply


def _persona():
    return Persona(
        name="King Aldric",
        source_prompt="queen-obsessed king",
        title="the Dependent",
        system_prompt="You are a blustering king.",
        greeting="I need no one!",
        catchphrases=("Where is she?",),
    )


def _bd(move, cp, *, allowed=True):
    return MoveBreakdown(
        move=move, cp_score=cp, action=0.0, state=0.0, trajectory=0.0,
        style=0.0, noise=0.0, total=float(cp), allowed=allowed,
    )


def test_system_prompt_carries_persona_and_rules():
    sp = build_system_prompt(_persona(), chess.WHITE)
    assert "blustering king" in sp
    assert "King Aldric (the Dependent)" in sp
    assert "White" in sp
    assert "never claim to" in sp.lower()
    assert "Where is she?" in sp  # catchphrase included


def test_greeting_comes_from_persona():
    chat = PersonaChat(_persona(), FakeChatLLM(), chess.WHITE)
    assert chat.greeting() == "I need no one!"


def test_quiet_move_produces_no_reaction_and_no_llm_call():
    llm = FakeChatLLM()
    chat = PersonaChat(_persona(), llm, chess.WHITE)
    board = chess.Board()
    move = chess.Move.from_uci("g1f3")  # quiet knight develop
    assert chat.react_to_move(board, move, [_bd(move, 20)]) is None
    assert llm.calls == []  # didn't waste an LLM call


def test_dramatic_move_triggers_grounded_reaction():
    llm = FakeChatLLM(reply="My queen takes yours! Bow!")
    chat = PersonaChat(_persona(), llm, chess.WHITE)
    board = chess.Board("3qk3/8/8/8/8/8/8/3QK3 w - - 0 1")
    move = board.parse_san("Qxd8+")
    out = chat.react_to_move(board, move, [_bd(move, 900)])
    assert out == "My queen takes yours! Bow!"
    # The LLM saw a grounded [GAME UPDATE] note as the latest user turn.
    _system, history = llm.calls[-1]
    assert history[-1].role == "user"
    assert "[GAME UPDATE]" in history[-1].content
    assert "Qxd8" in history[-1].content


def test_player_reply_appends_to_shared_history():
    llm = FakeChatLLM(reply="You dare mock me?")
    chat = PersonaChat(_persona(), llm, chess.WHITE)
    out = chat.reply_to_player("your king looks nervous")
    assert out == "You dare mock me?"
    _system, history = llm.calls[-1]
    assert history[-1] == ChatMessage(role="user", content="your king looks nervous")


def test_history_accumulates_across_turns():
    llm = FakeChatLLM()
    chat = PersonaChat(_persona(), llm, chess.WHITE)
    chat.reply_to_player("hi")
    chat.reply_to_player("still here?")
    # Second call should include the first user+model turns plus the new one.
    _system, history = llm.calls[-1]
    roles = [m.role for m in history]
    assert roles == ["user", "model", "user"]


def test_eval_swing_uses_previous_move_cp():
    llm = FakeChatLLM()
    chat = PersonaChat(_persona(), llm, chess.WHITE)
    board = chess.Board()
    quiet = chess.Move.from_uci("g1f3")
    # First (quiet) move: no reaction, but records prev_cp internally.
    chat.react_to_move(board, quiet, [_bd(quiet, 20)])
    # A later move with a big jump should now read as a swing and react.
    board2 = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    push = board2.parse_san("Qh5")
    chat.react_to_move(board2, push, [_bd(push, 400)])
    assert llm.calls, "a big eval swing should have triggered a reaction"
    _system, history = llm.calls[-1]
    assert "swing" in history[-1].content.lower()
