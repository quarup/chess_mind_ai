# ChessMind AI

A prompt-configurable chess AI that emulates different playing styles and difficulty levels. Built on top of a strong existing engine (Stockfish), with a style-scoring layer that biases move selection toward natural-language style preferences such as *"aggressively use your queen"* or *"only play on the queenside."*

The long-term vision is for ChessMind AI to support voice and conversational interaction, letting users describe an opponent and then play, talk, and iterate naturally. See [plan.md](plan.md) for the full design.

## Current status

**Milestones 1 + 2 + 3**: a Python chess engine wrapper with a hand-coded *queen-obsessed* style scorer, Elo-based candidate filtering, a terminal CLI for playing against the bot, and **LLM-generated style scorers** via a provider-abstracted layer (default: Google Gemini 2.5 Flash-Lite, free tier).

Subprocess sandboxing and the UCI engine wrapper land in later milestones.

## Requirements

- Python 3.11+
- [Stockfish](https://stockfishchess.org/) on `PATH` (e.g. `brew install stockfish`)
- [`uv`](https://docs.astral.sh/uv/) for dependency management

## Quick start

```bash
uv sync
# Hand-coded queen-obsessed bot (no API key needed):
uv run chess-mind-ai play --color white --elo 1500 --explain

# Prompt-driven bot (free Gemini API key from https://aistudio.google.com/apikey):
export GEMINI_API_KEY=your-key-here
uv run chess-mind-ai play --prompt "play very defensively, never trade queens"
```

Type moves in [Standard Algebraic Notation](https://en.wikipedia.org/wiki/Algebraic_notation_(chess)) — e.g. `e4`, `Nf3`, `O-O`. Type `quit` to exit.

### Flags

- `--color {white,black}` — which color you play (default: `white`)
- `--elo N` — target rating for the AI (default: `1500`)
- `--prompt "..."` — natural-language style description; an LLM generates the scorer code (requires `GEMINI_API_KEY`). Without this flag the hand-coded queen-obsessed scorer is used.
- `--llm-model NAME` — override the default Gemini model (`gemini-2.5-flash-lite`)
- `--show-generated-code` — print the LLM-generated scorer source before the game starts
- `--explain` — print per-candidate score breakdown each AI move

### LLM providers

The default provider is Google Gemini, on its free tier. Anthropic and OpenAI are planned drop-in alternatives behind the same `StyleScorerLLM` protocol — see [`docs/llm-providers.md`](docs/llm-providers.md) for pricing, free-tier terms, and the data-usage caveat.

## Tests

```bash
uv run pytest
uv run ruff check
```

## Architecture (M1 + M2)

```
User CLI / UCI (future)
        ↓
Stockfish (top-N candidates via MultiPV)
        ↓
SafeChessContext  →  style scorer (action + state + trajectory)
        ↓
Selector: engine score + style score, filtered by Elo centipawn budget
        ↓
Chosen move
```

## License

MIT. See [LICENSE](LICENSE).
