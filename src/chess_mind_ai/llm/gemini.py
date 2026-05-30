"""Google Gemini adapters.

`GeminiProvider` implements `StyleScorerLLM` (one-shot scorer-code generation
and any other one-shot text task, e.g. persona-sheet generation).
`GeminiChatProvider` implements `ChatLLM` (multi-turn in-character banter).

Default model is `gemini-2.5-flash-lite` — the cheapest tier and the one
Google's free tier currently allows the highest request rate on. See
`docs/llm-providers.md`.
"""
from __future__ import annotations

import os

from chess_mind_ai.llm.protocol import ChatMessage

DEFAULT_MODEL = "gemini-2.5-flash-lite"
# Chat benefits from a slightly stronger model for personality, but we keep the
# free-tier default and let callers bump it (e.g. to "gemini-2.5-flash").
DEFAULT_CHAT_MODEL = "gemini-2.5-flash-lite"


def _resolve_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get a free key at "
            "https://aistudio.google.com/apikey and export it:\n"
            "    export GEMINI_API_KEY=your-key-here"
        )
    return key


def _make_client(api_key: str | None):
    # Lazy-import so users without google-genai installed can still load the
    # package (e.g. when running the hand-coded queen-obsessed bot).
    from google import genai

    return genai.Client(api_key=_resolve_key(api_key))


class GeminiProvider:
    """One-shot text generation (`StyleScorerLLM`)."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
    ):
        self._model = model
        self._client = _make_client(api_key)

    def generate(
        self,
        system: str,
        user: str,
        *,
        max_output_tokens: int = 2048,
    ) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_output_tokens,
                temperature=0.3,
            ),
        )
        text = response.text
        if not text:
            raise RuntimeError(
                f"Gemini ({self._model}) returned an empty response. "
                "Try a different prompt or increase --max-output-tokens."
            )
        return text


class GeminiChatProvider:
    """Multi-turn in-character chat (`ChatLLM`)."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_CHAT_MODEL,
        api_key: str | None = None,
    ):
        self._model = model
        self._client = _make_client(api_key)

    def chat(
        self,
        system: str,
        messages: list[ChatMessage],
        *,
        max_output_tokens: int = 512,
        temperature: float = 0.9,
    ) -> str:
        from google.genai import types

        contents = [
            types.Content(role=m.role, parts=[types.Part(text=m.content)])
            for m in messages
        ]
        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            ),
        )
        text = response.text
        if not text:
            raise RuntimeError(
                f"Gemini chat ({self._model}) returned an empty response."
            )
        return text.strip()
