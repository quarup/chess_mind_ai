from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class StyleScorerLLM(Protocol):
    """One-shot text-in / text-out interface for scorer-code generation."""

    def generate(
        self,
        system: str,
        user: str,
        *,
        max_output_tokens: int = 2048,
    ) -> str: ...


@dataclass(frozen=True)
class ChatMessage:
    """One turn of a persona chat. `role` is "user" (the human, or an injected
    [GAME UPDATE] note) or "model" (the in-character bot)."""

    role: str
    content: str


class ChatLLM(Protocol):
    """Multi-turn chat interface for in-character persona banter.

    Distinct from `StyleScorerLLM` (one-shot code generation) because chat needs
    conversation history and runs warmer. Providers map `messages` onto their
    own multi-turn API; `system` is the persona's standing instruction.
    """

    def chat(
        self,
        system: str,
        messages: list[ChatMessage],
        *,
        max_output_tokens: int = 512,
        temperature: float = 0.9,
    ) -> str: ...
