from __future__ import annotations

import json

from chess_mind_ai.persona.spec import Persona

PROMPT = "a king helpless without his queen; attacks with the queen early"


def test_parses_full_sheet():
    sheet = json.dumps(
        {
            "name": "King Aldric",
            "title": "the Dependent",
            "system_prompt": "You are a blustering king.",
            "greeting": "I need no one!",
            "catchphrases": ["Where is she?", "I am invincible!"],
            "voice_design": "gravelly, arrogant",
            "image_prompt": "oil portrait of an aging chess king",
        }
    )
    p = Persona.from_json(sheet, source_prompt=PROMPT)
    assert p.name == "King Aldric"
    assert p.title == "the Dependent"
    assert p.display_name() == "King Aldric (the Dependent)"
    assert p.greeting == "I need no one!"
    assert p.catchphrases == ("Where is she?", "I am invincible!")
    assert p.voice_design == "gravelly, arrogant"
    assert p.source_prompt == PROMPT


def test_tolerates_json_fence():
    sheet = '```json\n{"name": "Sir Fork", "system_prompt": "You are a knight."}\n```'
    p = Persona.from_json(sheet, source_prompt=PROMPT)
    assert p.name == "Sir Fork"
    assert p.system_prompt == "You are a knight."


def test_extracts_object_from_surrounding_prose():
    sheet = 'Sure! Here is your character:\n{"name": "Boris"}\nHope you like it.'
    p = Persona.from_json(sheet, source_prompt=PROMPT)
    assert p.name == "Boris"


def test_missing_system_prompt_is_synthesized_from_prompt():
    p = Persona.from_json('{"name": "Nameless"}', source_prompt=PROMPT)
    assert PROMPT in p.system_prompt
    assert "Nameless" in p.system_prompt


def test_malformed_json_falls_back():
    p = Persona.from_json("this is not json at all", source_prompt=PROMPT)
    assert p.name == "The Opponent"
    assert PROMPT in p.system_prompt
    assert p.greeting  # always has something to say


def test_empty_falls_back():
    p = Persona.from_json("", source_prompt=PROMPT)
    assert p.name == "The Opponent"


def test_catchphrases_coerced_and_filtered():
    sheet = json.dumps({"name": "X", "catchphrases": ["ok", "", 5, "  trim  "]})
    p = Persona.from_json(sheet, source_prompt=PROMPT)
    assert p.catchphrases == ("ok", "trim")


def test_display_name_without_title():
    p = Persona.from_json('{"name": "Solo"}', source_prompt=PROMPT)
    assert p.display_name() == "Solo"
