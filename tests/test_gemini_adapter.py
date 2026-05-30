"""Contract tests for the Gemini adapters that don't require an API key.

These lock the import surface that `cli.py` / `uci.py` depend on, so a missing
symbol (e.g. GeminiChatProvider) fails here instead of only at runtime when a
user passes --chat.
"""
from __future__ import annotations

import pytest

from chess_mind_ai.llm import gemini
from chess_mind_ai.llm.protocol import ChatLLM, StyleScorerLLM


def test_expected_symbols_exist():
    assert isinstance(gemini.DEFAULT_MODEL, str)
    assert isinstance(gemini.DEFAULT_CHAT_MODEL, str)
    assert hasattr(gemini, "GeminiProvider")
    assert hasattr(gemini, "GeminiChatProvider")


def test_providers_match_protocols():
    # Structural typing: the classes satisfy their protocols' method shape.
    assert hasattr(gemini.GeminiProvider, "generate")
    assert hasattr(gemini.GeminiChatProvider, "chat")
    # Protocols are importable and usable as annotations.
    assert StyleScorerLLM is not None
    assert ChatLLM is not None


def test_missing_api_key_raises_clearly(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        gemini.GeminiProvider()
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        gemini.GeminiChatProvider()
