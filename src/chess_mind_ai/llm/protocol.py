from __future__ import annotations

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
