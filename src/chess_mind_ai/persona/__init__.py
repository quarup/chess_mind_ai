"""Character / persona layer (plan.md Milestone 9, Phase A).

Turns the *same* natural-language prompt that drives the style scorer into a
playable character: a persona sheet (`spec.Persona`), a game-grounded chat
session (`chat.PersonaChat`), and the narration that feeds it
(`narration`, built from the selector's `MoveBreakdown`). Voice and image
generation are later phases; see `docs/persona-design.md`.
"""
