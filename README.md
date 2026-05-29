# ChessMind AI

A prompt-configurable chess AI that emulates different playing styles and difficulty levels. Built on top of a strong existing engine (Stockfish), with a style-scoring layer that biases move selection toward natural-language style preferences such as *"aggressively use your queen"* or *"only play on the queenside."*

The long-term vision is for ChessMind AI to support voice and conversational interaction, letting users describe an opponent and then play, talk, and iterate naturally. See [plan.md](plan.md) for the full design.

## Current status

**Milestones 1 + 2 + 3**: a Python chess engine wrapper with a hand-coded *queen-obsessed* style scorer, Elo-based candidate filtering, a terminal CLI for playing against the bot, and **LLM-generated style scorers** via a provider-abstracted layer (default: Google Gemini 2.5 Flash-Lite, free tier).

**Milestone 4 (in progress)**: LLM-generated scorers now run in an **isolated worker process** — separate process, `setrlimit` memory/CPU caps, a wall-clock timeout, a scrubbed environment, and unprivileged `unshare` network/mount isolation on Linux — falling back to neutral engine play if the sandbox fails. See [`docs/scorer-sandbox-design.md`](docs/scorer-sandbox-design.md).

**Milestone 5**: the bot now speaks **UCI**, so it plugs into chess GUIs (Cute Chess, Arena) and match runners (cutechess-cli). Style prompt and target Elo are configured through UCI options. See [Playing in a GUI](#playing-in-a-gui-uci) below.

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

## Playing in a GUI (UCI)

ChessMind AI speaks the [UCI protocol](https://en.wikipedia.org/wiki/Universal_Chess_Interface), so you can load it into a chess GUI like [Cute Chess](https://cutechess.com/) or Arena, or run engine-vs-engine matches with `cutechess-cli`.

**See [`docs/playing-in-cutechess.md`](docs/playing-in-cutechess.md)** for a full step-by-step on installing Cute Chess (including the macOS build-from-source recipe), registering ChessMind AI + Stockfish as engines, playing human-vs-AI games, configuring prompt-driven personalities, and running headless tournaments with `cutechess-cli`.

The shortest path: point your GUI at the `./uci` launcher script (it handles the venv) or run the console script directly:

```bash
uv run chess-mind-ai-uci      # or: ./uci   (also: uv run chess-mind-ai uci)
```

Configure style and strength through UCI options (your GUI exposes these in its engine settings; `cutechess-cli` takes them as `option.Name=value`):

| Option | Type | Meaning |
| --- | --- | --- |
| `Prompt` | string | Natural-language style. Empty = hand-coded queen-obsessed bot. A non-empty prompt generates an LLM scorer (needs `GEMINI_API_KEY`). |
| `UCI_Elo` | spin | Target rating (controls how far style may stray from the engine's best move). |
| `UCI_LimitStrength` | check | Off → play full strength (ignore the Elo blunder budget). |
| `Stockfish Path` | string | Path to the Stockfish binary (default: `stockfish` on `PATH`). |
| `MultiPV` | spin | Candidate count; `0` = auto-scale from Elo. |
| `Move Time` | spin | Default think time per move in ms when the GUI doesn't send `go movetime`. |
| `LLM Model` | string | Override the Gemini model. |
| `Style Weight` | spin | How much one style unit is worth, in centipawns (default `30`). |

The scorer is generated **eagerly at `isready`** (before the clock starts) and cached for the game. Move timing honors an explicit `go movetime`, otherwise uses `Move Time`; full clock budgeting from `wtime`/`btime` arrives in M6.

### LLM providers

The default provider is Google Gemini, on its free tier. Anthropic and OpenAI are planned drop-in alternatives behind the same `StyleScorerLLM` protocol — see [`docs/llm-providers.md`](docs/llm-providers.md) for pricing, free-tier terms, and the data-usage caveat.

## Tests

```bash
uv run pytest
uv run ruff check
```

## Architecture

```
Terminal CLI  /  UCI engine (GUIs, cutechess-cli)
        ↓
Stockfish (top-N candidates via MultiPV)
        ↓
ReadOnlyBoard  →  style scorer (action + state + trajectory)
                  (LLM-generated code runs in a sandboxed worker)
        ↓
Selector: engine score + style score, filtered by Elo centipawn budget
        ↓
Chosen move
```

## License

MIT. See [LICENSE](LICENSE).
