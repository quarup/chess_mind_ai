from __future__ import annotations

import textwrap

import pytest

from chess_mind_ai.llm.prompt import SYSTEM_PROMPT, extract_code


def test_system_prompt_mentions_required_functions():
    for fn in ("action_score", "state_score", "trajectory_score"):
        assert fn in SYSTEM_PROMPT


def test_extract_strips_python_fence():
    wrapped = textwrap.dedent("""
        ```python
        def action_score(ctx, move):
            return 1.0
        ```
    """).strip()
    body = extract_code(wrapped)
    assert body.startswith("def action_score")
    assert "```" not in body


def test_extract_strips_bare_fence():
    wrapped = "```\nprint(1)\n```"
    assert extract_code(wrapped) == "print(1)"


def test_extract_passes_through_unfenced():
    plain = "def action_score(ctx, move):\n    return 0.0\n"
    assert extract_code(plain) == plain.strip()


def test_extract_rejects_none():
    with pytest.raises(ValueError):
        extract_code(None)  # type: ignore[arg-type]
