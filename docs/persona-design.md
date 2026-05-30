# ChessMind AI — Character / Persona Design

> **Status (2026-05):** Phase A (persona generation + game-grounded **text**
> chat) is implemented and wired into `./play --chat`. Voice and image are
> designed here but not yet built. This is plan.md **Milestone 9**, which we
> prioritized ahead of M6 (AI-vs-AI evaluation).

## 1. Goal

Turn ChessMind from "a bot with a *style*" into "a bot with a *character*."
The queen-obsessed bot shouldn't just play queen moves — it should *be* a
blustering king who is secretly helpless without his queen, who gloats when she
rampages and panics when she's threatened, talks back to you, has a face, and
(later) a voice.

## 2. Core idea — one prompt, many artifacts

The user writes **one** prompt that mixes *how it plays* with *who it is*:

> "a king who acts tough but is clearly helpless without his queen; plays
> aggressively, attacks with the queen early."

That single prompt fans out:

```
character_prompt
      │
      ├─ scorer generator  → Python scoring code   (existing: llm/prompt.py)
      └─ persona generator → character sheet        (new: persona/prompt.py)
                               ├─ system_prompt (the actor's instruction)
                               ├─ greeting + catchphrases
                               ├─ voice_design  (consumed in Phase C)
                               └─ image_prompt  (consumed in Phase B)
```

Each artifact is generated once and cached. A future **character gallery** is
then just a database of prompts, each expanding into a fully-realized opponent
(code + face + voice + banter).

## 3. The differentiator — ground the chat in the *real* game

Generic "AI personality" gimmicks fall flat because the chatter doesn't know
what's happening on the board. We can do much better for free, because the
selector already computes the bot's actual reasoning: `MoveBreakdown` (per
candidate: engine centipawns, style score, whether it was within the Elo
budget). See `selector.py`.

`persona/narration.py` turns the move just played + the breakdown into a
`GameMoment` and a compact `[GAME UPDATE]` digest fed to the chat LLM:

```
[GAME UPDATE]
You are White. It is move 4.
You just played Qxf7#.
CHECKMATE — you just WON the game!
You moved your queen.
It CAPTURES the enemy pawn.
Engine evaluation now: +10000 cp (you are winning).
Your queen is alive; the enemy queen is alive.
Your style made you pick this over the safer Nf3 (+30 cp).
React in character, 1-2 short sentences. Do not narrate like a commentator; feel it.
```

So the trash talk is *true*: "I sent **her** in — Nf3 was the coward's 30
points, but where's the glory in that?" That `passed_up` line comes straight
from the rejected candidates in the breakdown. This is the moat: a character
that understands its own game, not a chatbot bolted onto a chess engine.

## 4. When does it talk?

Two input streams feed **one** conversation history so banter stays coherent
(`persona/chat.py`):

- **Move reactions** (`react_to_move`) — fire only on *dramatic* events
  (`narration.is_dramatic`): checkmate, check, capturing/losing the queen,
  leaving the queen hanging, big eval swings. Quiet developing moves stay
  silent — and don't even spend an LLM call.
- **Player messages** (`reply_to_player`) — always answered. In the CLI you
  type `say <message>` on your turn.

The system prompt (`build_system_prompt`) pins the character, caps replies at
1–3 sentences, forbids breaking the fourth wall, and — importantly — forbids
claiming to calculate variations, because the bot does **not** pick its own
moves; it reacts to outcomes.

## 5. Robustness

Banter is never allowed to break a game (plan §14):

- Malformed persona JSON → `Persona.fallback` (a generic but usable character).
- Missing `GEMINI_API_KEY` or any chat error → chat silently disabled; the game
  plays on.
- `--chat` without `--prompt` → warned and skipped (no prompt, no personality).

## 6. Provider abstraction

Chat is a different *shape* than scorer generation (multi-turn + streaming-ish,
warmer), so it gets its own protocol rather than overloading `StyleScorerLLM`:

- `llm/protocol.py`: `ChatMessage` + `ChatLLM` (`chat(system, messages, ...)`).
- `llm/gemini.py`: `GeminiChatProvider`. Persona-sheet generation is one-shot,
  so it reuses the existing `GeminiProvider.generate`.

Default stays `gemini-2.5-flash-lite` (free tier, no credit card — same
rationale as the scorer layer; see `docs/llm-providers.md`). A stronger model
(e.g. `gemini-2.5-flash`) gives livelier personality and is selectable via
`--chat-model`.

## 7. Voice (Phase C) — designed, not yet built

Two halves: **TTS** (bot speaks) and **STT** (you speak). Chess pacing is
forgiving — banter happens *between* moves — so a **pipeline** (STT → LLM → TTS)
beats realtime speech-to-speech APIs: it gives full per-character voice control
and is simpler/cheaper, and the latency is fine.

We want it playable with **no API key**, so TTS becomes a provider-abstracted
adapter (mirroring `llm/`) that defaults to a local open-source backend, with a
hosted high-quality option opt-in:

| Backend | Type | Notes |
|---|---|---|
| **Kokoro** (Apache) | preset voices | tiny, fast, trivial to run — good default |
| **Chatterbox** (MIT) | clone from reference clip | expressive; best OSS quality |
| **XTTS-v2** | clone from reference clip | mature, multilingual |
| **Parler-TTS** | **design from text** | maps `voice_design` directly; lower fidelity |
| **ElevenLabs** | hosted, text voice design | best quality + true text design; opt-in |

Honest tradeoff: ElevenLabs is the only option that is simultaneously high
quality, effortless, and able to *design a voice from a text description*. OSS
character voices trail it but are "good enough to be fun." Auto-designing a
voice from `voice_design`: Parler-TTS does it directly; the cloners need a
reference clip (archetype bank or generated sample). **STT is solved OSS** —
Whisper / faster-whisper / whisper.cpp run locally and are excellent.

Suggested default: Kokoro (instant) or Chatterbox (cloning) local; ElevenLabs
via `TTS_BACKEND=elevenlabs`.

## 8. Image (Phase B) — designed, not yet built

Generate a portrait from `image_prompt`, once, cached to disk. Path of least
resistance is **Gemini / Imagen** (we already have the key). Alternatives:
OpenAI `gpt-image-1`, or local Flux/SD for the no-key path. Nice later upgrade:
a few **expression variants** (confident / worried / defeated) keyed to the
`GameMoment` mood, so the portrait reacts as the queen gets hunted.

## 9. Where the experience lives — the app

UCI is a *move* protocol; chess GUIs (Cute Chess, Arena) have **no** channel for
voice, images, or an avatar. So:

- Keep **UCI headless** for engine-vs-engine evaluation (M6) and a Lichess bot
  (M8) — personality doesn't belong there.
- Build the character experience in **our own small web app** (plan M7,
  effectively merged with this work): reuse OSS *components* — **chessground**
  (Lichess's board, MIT) + **chess.js** — and surround the board with the
  portrait panel, a chat bubble, and push-to-talk. **Don't fork** a whole app
  (e.g. Lichess); just reuse its board widget.

```
                 engine + selector + sandbox (existing core)
                 /                                 \
   "Competition face" = UCI            "Character face" = web app
   (cutechess M6, Lichess M8)          (persona + voice + image + chat)
```

The terminal `./play --chat` is the Phase-A proving ground for the character
face before we invest in the web UI.

## 10. Phasing

- **A — Persona + grounded text chat.** *(done)* `persona/` package +
  `./play --chat`.
- **B — Portrait.** Generate + cache an image from `image_prompt`.
- **C — Voice.** TTS adapter (OSS default, ElevenLabs opt-in) + STT (Whisper).
- **D — Web app.** chessground UI with portrait, chat, and push-to-talk over a
  websocket session backend.
- **E — Polish.** Expression variants, optional realtime speech, character
  gallery / prompt database.

## 11. As-built map (Phase A)

| File | Role |
|---|---|
| `llm/protocol.py` | `ChatMessage`, `ChatLLM` protocol |
| `llm/gemini.py` | `GeminiChatProvider` (+ shared client helper) |
| `persona/spec.py` | `Persona` sheet + tolerant JSON parse + fallback |
| `persona/prompt.py` | persona-generation system prompt |
| `persona/narration.py` | `GameMoment` + `[GAME UPDATE]` digest from `MoveBreakdown` |
| `persona/chat.py` | `PersonaChat` session (reactions + replies, shared history) |
| `cli.py` | `--chat` / `--chat-model`, `say <msg>`, reaction printing |

Try it:

```bash
export GEMINI_API_KEY=...
./play --prompt "a king who acts tough but is helpless without his queen; \
  attacks aggressively with the queen" --elo 1400 --chat
```
