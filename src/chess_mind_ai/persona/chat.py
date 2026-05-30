"""A game-grounded, in-character chat session.

Holds one conversation with the persona for the duration of a game. Two input
streams feed the same history so reactions stay coherent (plan: react on
dramatic events, and reply when the player says something):

  * `react_to_move(...)` — called after every bot move; emits a quip only when
    the move was dramatic (see `narration.is_dramatic`), otherwise stays quiet.
  * `reply_to_player(...)` — always answers the human's message.

The bot does not choose moves, so the system prompt forbids it from claiming to
calculate; it reacts to outcomes the `narration` digest hands it.
"""
from __future__ import annotations

import chess

from chess_mind_ai.llm.protocol import ChatLLM, ChatMessage
from chess_mind_ai.persona.narration import describe_move, digest, is_dramatic
from chess_mind_ai.persona.spec import Persona
from chess_mind_ai.selector import MoveBreakdown

# Keep the prompt bounded on long games (most recent turns carry the banter).
_HISTORY_LIMIT = 24


def build_system_prompt(persona: Persona, own_color: chess.Color) -> str:
    color = "White" if own_color == chess.WHITE else "Black"
    catch = ""
    if persona.catchphrases:
        catch = "\nSome of your catchphrases: " + " / ".join(persona.catchphrases)
    return (
        f"{persona.system_prompt}\n\n"
        f"You are {persona.display_name()}, playing a game of chess as {color} "
        "against a human and trash-talking / chatting with them via text.\n"
        "Rules:\n"
        "- Always stay in character. Never say you are an AI, a model, or a "
        "program, and never break the fourth wall.\n"
        "- Keep replies to 1-3 short sentences. This is banter, not an essay.\n"
        "- You will sometimes get [GAME UPDATE] notes describing what just "
        "happened on the board. Treat them as ground truth, react emotionally, "
        "and never invent moves that did not happen.\n"
        "- You do NOT choose the chess moves yourself, so never claim to "
        "calculate lines or variations; react to outcomes — gloat, panic, "
        "taunt, despair."
        f"{catch}"
    )


class PersonaChat:
    def __init__(
        self,
        persona: Persona,
        llm: ChatLLM,
        own_color: chess.Color,
        *,
        history_limit: int = _HISTORY_LIMIT,
    ) -> None:
        self.persona = persona
        self._llm = llm
        self._own_color = own_color
        self._system = build_system_prompt(persona, own_color)
        self._history: list[ChatMessage] = []
        self._history_limit = history_limit
        self._prev_cp: int | None = None

    def greeting(self) -> str:
        return self.persona.greeting

    def react_to_move(
        self,
        board_before: chess.Board,
        move: chess.Move,
        breakdown: list[MoveBreakdown],
    ) -> str | None:
        """In-character reaction to the bot's own move, or None if undramatic."""
        moment = describe_move(
            board_before, move, breakdown, self._own_color, prev_cp=self._prev_cp
        )
        self._prev_cp = moment.cp_score
        if not is_dramatic(moment):
            return None
        return self._exchange(digest(moment))

    def reply_to_player(self, text: str) -> str:
        """In-character reply to something the human typed."""
        return self._exchange(text)

    def _exchange(self, user_content: str) -> str:
        self._history.append(ChatMessage(role="user", content=user_content))
        reply = self._llm.chat(self._system, self._history[-self._history_limit :])
        self._history.append(ChatMessage(role="model", content=reply))
        return reply
