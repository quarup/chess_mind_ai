"""Google Gemini adapter for `StyleScorerLLM`.

Default model is `gemini-2.5-flash-lite` — the cheapest tier and the one
Google's free tier currently allows the highest request rate on. See
`docs/llm-providers.md`.
"""
from __future__ import annotations

import os

DEFAULT_MODEL = "gemini-2.5-flash-lite"


class GeminiProvider:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
    ):
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey and export it:\n"
                "    export GEMINI_API_KEY=your-key-here"
            )
        # Lazy-import so users without google-genai installed can still load
        # the package (e.g. when running the hand-coded queen-obsessed bot).
        from google import genai

        self._model = model
        self._client = genai.Client(api_key=key)

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
