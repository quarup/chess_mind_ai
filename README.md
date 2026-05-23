# ChessMind AI

A prompt-configurable chess AI that emulates different playing styles and difficulty levels. Built on top of a strong existing engine (Stockfish), with a style-scoring layer that biases move selection toward natural-language style preferences such as *"aggressively use your queen"* or *"only play on the queenside."*

The long-term vision is for ChessMind AI to support voice and conversational interaction, letting users describe an opponent and then play, talk, and iterate naturally. See [plan.md](plan.md) for the full design.

## Current status

**Milestones 1 + 2** (this version): a Python chess engine wrapper with a hand-coded *queen-obsessed* style scorer, Elo-based candidate filtering, and a tiny terminal CLI for playing against the bot.

LLM-generated scorers, sandboxing, and the UCI engine wrapper land in later milestones.

## Requirements

- Python 3.11+
- [Stockfish](https://stockfishchess.org/) on `PATH` (e.g. `brew install stockfish`)
- [`uv`](https://docs.astral.sh/uv/) for dependency management

## Quick start

```bash
uv sync
uv run chess-mind-ai play --color white --elo 1500 --explain
```

Type moves in [Standard Algebraic Notation](https://en.wikipedia.org/wiki/Algebraic_notation_(chess)) — e.g. `e4`, `Nf3`, `O-O`. Type `quit` to exit.

### Flags

- `--color {white,black}` — which color you play (default: `white`)
- `--elo N` — target rating for the AI (default: `1500`)
- `--prompt "..."` — reserved for future LLM-generated style; currently ignored (always queen-obsessed)
- `--explain` — print per-candidate score breakdown each AI move

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
