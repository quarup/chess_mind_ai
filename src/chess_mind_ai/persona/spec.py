"""The persona sheet: a character generated from the user's style prompt.

One prompt (e.g. "a king who acts tough but is helpless without his queen;
attacks aggressively with the queen") expands into both a *scorer* (how it
plays) and a *persona* (who it is). This module models the persona half and
parses it from the LLM's JSON output, tolerantly and with a safe fallback so a
malformed sheet never aborts a game.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(?P<body>.*?)\n```", re.DOTALL)


@dataclass(frozen=True)
class Persona:
    """A chess character. `system_prompt` is the standing instruction that makes
    the chat LLM speak in character; the rest are display/voice/image metadata
    (voice and image are consumed in later phases)."""

    name: str
    source_prompt: str
    title: str = ""
    system_prompt: str = ""
    greeting: str = "Let's play."
    catchphrases: tuple[str, ...] = ()
    voice_design: str = ""
    image_prompt: str = ""

    @classmethod
    def fallback(cls, source_prompt: str) -> Persona:
        """A generic-but-usable persona when generation/parsing fails, so chat
        still works (plan §14, "always have a neutral fallback")."""
        return cls(
            name="The Opponent",
            source_prompt=source_prompt,
            system_prompt=(
                "You are a chess opponent with this style and personality: "
                f"{source_prompt}. Stay in character while you play and chat."
            ),
            greeting="Let's play.",
        )

    @classmethod
    def from_json(cls, text: str, *, source_prompt: str) -> Persona:
        """Parse a persona sheet from LLM JSON output. Tolerates a ```json fence
        and missing keys; returns `fallback` on any structural failure."""
        data = _loads_tolerant(text)
        if not isinstance(data, dict):
            return cls.fallback(source_prompt)

        name = _as_str(data.get("name")) or "The Opponent"
        system_prompt = _as_str(data.get("system_prompt"))
        if not system_prompt:
            # Build a serviceable instruction from whatever fields we got.
            system_prompt = (
                f"You are {name}. You are a chess opponent with this style and "
                f"personality: {source_prompt}. Stay in character."
            )
        return cls(
            name=name,
            source_prompt=source_prompt,
            title=_as_str(data.get("title")),
            system_prompt=system_prompt,
            greeting=_as_str(data.get("greeting")) or "Let's play.",
            catchphrases=_as_str_tuple(data.get("catchphrases")),
            voice_design=_as_str(data.get("voice_design")),
            image_prompt=_as_str(data.get("image_prompt")),
        )

    def display_name(self) -> str:
        return f"{self.name} ({self.title})" if self.title else self.name


def _loads_tolerant(text: str | None):
    if not text:
        return None
    match = _FENCE_RE.search(text)
    candidate = match.group("body") if match else text
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        # Last resort: grab the outermost {...} block and try again.
        start, end = candidate.find("{"), candidate.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(candidate[start : end + 1])
            except (json.JSONDecodeError, TypeError):
                return None
        return None


def _as_str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(v.strip() for v in value if isinstance(v, str) and v.strip())
    return ()
