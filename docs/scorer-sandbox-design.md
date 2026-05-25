# Scorer Context & Sandbox Design

> Status: **decided**, partially implemented. This document captures a design
> discussion (2026-05) about how generated style scorers should see the board
> and how we keep that safe. It is the reference for future sessions — read it
> before changing `sandbox/validator.py`, `readonly_board.py`, `context.py`, or
> the M4 sandbox work.

## 1. The problem

The M2/M3 scorer interface, `SafeChessContext` (`src/chess_mind_ai/context.py`),
exposes ~12 hand-picked, mostly queen-shaped scalar queries
(`piece_mobility("queen")`, `is_capture(move)`, `count_own_moves_by_piece(...)`,
etc.). That surface is the **bottleneck on expressiveness**: an LLM asked for
"advance your pawns aggressively" cannot reward pawn advancement, because no
context method describes it. The generated code looks limited because the
*vocabulary it is allowed to speak* is limited.

So the real question isn't "write a better prompt" — it's **how much of the
board do we expose to generated scorers, and how do we keep that safe.**

## 2. What python-chess is (and why we didn't just hand it over)

`python-chess` (`import chess`) is the standard chess library and already a
dependency (`engine.py` uses it). It provides `chess.Board` (legality, move
generation, `attackers()`, `piece_at()`, FEN/PGN, push/pop), `chess.Move`,
`chess.engine` (talks UCI to Stockfish), plus opening-book / tablebase / SVG
modules.

The instinct "just give the scorer the `Board`" is reasonable but has costs:

1. **Sandbox escape.** A live `Board` is a gateway to the interpreter:
   `board.__class__.__init__.__globals__['__builtins__']['__import__']` reaches
   `os`. This is the classic Python escape.
2. **Mutation.** A `Board` is mutable; generated code could call
   `board.push()` / `set_fen()` and corrupt the game state the selector is
   looping over.
3. **Unstable, unvalidatable contract.** The python-chess API is large and
   version-dependent; arbitrary `board.*` calls mean the LLM must know the
   whole library (or it hallucinates), and an upgrade can silently break old
   scorers.
4. **Performance / explainability.** Scalars can be precomputed and cached;
   a bounded vocabulary keeps scorers readable and loggable.

## 3. The key security insight

**Safety has almost nothing to do with *which object* we hand over.**
`SafeChessContext` is itself a live Python object — `ctx.__class__...__globals__`
reaches `os` exactly like a `Board` would. Wrapping the board does **not**, by
itself, make the escape harder.

What actually contains generated code is a different layer:

- **The AST validator + restricted builtins**, which act on the *source text*
  before it runs. They forbid the *syntax* needed to walk the object graph
  (any dunder/underscore attribute, `getattr`/`eval`/`exec`/`__import__`,
  imports, …). So `ctx.__class__` can't be written regardless of what `ctx`
  is. **Board and context are protected equally by this layer.**

Corollary: the "narrow context is safer than a board" argument is weak for
*escape*. The narrow context's genuine wins are **mutation-safety,
validatability, precomputation, and API stability** — not escape.

## 4. The AST validator is a denylist with holes → make it an allowlist

A denylist over a Turing-complete language fails *open*: it only rejects what
we thought to name. Concrete hole in the original validator:

```python
def state_score(ctx):
    return len("{0.__class__.__init__.__globals__[__builtins__]}".format(ctx))
```

The dunders live **inside a string literal**, so there is no `ast.Attribute`
node to catch; `.format` isn't a banned name; the format machinery does the
attribute traversal at runtime. This worked against the old validator.

**Fix (implemented):** flip the validator to an **allowlist** of AST node types
(fail closed on anything not explicitly permitted), and add guards:

- Only an enumerated set of node types is allowed (`_ALLOWED_NODES`). Imports,
  `class`, `lambda`, `with`, `try`, `global`/`nonlocal`, `del`, `yield`,
  `await`, async defs, walrus, **f-strings**, etc. all fail closed.
- Reject **any leading-underscore attribute** (`x._anything`), not just
  dunders. This blocks the object-graph escape *and* access to a facade's
  private `_board`.
- Reject **string literals containing `__`** (closes the `str.format`
  dunder-smuggling route).
- Reject the `format` / `format_map` attribute methods (belt-and-suspenders
  for runtime-assembled format strings).
- Keep the banned-builtin name/call list and the "exactly the three required
  functions" check.

See `src/chess_mind_ai/sandbox/validator.py` and `tests/test_validator.py`.

**This in-process layer is still best-effort, not the wall.** It is now much
harder to bypass, but the real boundary must be the OS sandbox (next section).

## 5. The decision: option C + OS sandbox as the real boundary

We considered four points on a spectrum for the scorer's view of the board:

| | Interface | Expressiveness | Notes |
|---|---|---|---|
| **A** | Narrow scalar API (today's `SafeChessContext`) | low | safe-feeling but caps prompts |
| **B** | Richer curated scalar API | medium | same style, bigger feature list |
| **C** | **Read-only board facade + curated `chess` namespace** | high | LLM composes primitives |
| **D** | Raw `python-chess` Board | max | abandons in-process sandbox entirely |

**Chosen: C, on the explicit assumption that the OS-level sandbox (M4) is the
real security boundary.** Rationale:

- Since the in-process layer isn't the true wall anyway (§3), C doesn't
  meaningfully reduce security versus B.
- C removes the expressiveness cap: new prompts rarely need a new method,
  because the scorer composes primitives (`attackers`, `attacks`, `piece_at`,
  square geometry, history) itself.
- **Hybrid:** keep a *small* set of precomputed scalar features for things that
  are expensive or fuzzy to compute in a generated hot loop (king safety, pawn
  structure). Don't make the LLM rebuild attack maps 40× per move when we can
  hand it a number.

This is only sound **if we commit to hardening M4**. That commitment is the
load-bearing part of the decision.

## 6. The read-only board facade (`readonly_board.py`)

Implemented: `ReadOnlyBoard` wraps a private *copy* of a `chess.Board` and
`own_color`, exposes read-only primitives only, and raises on attribute
assignment (`__setattr__`/`__delattr__`). Squares are plain ints (a1=0),
colors are bools (white=`True`), piece types are ints (1..6). It never returns
the underlying mutable board.

Surface (first cut — expand as `prompt_minds.md` motivates):

- Position: `own_color`, `turn`, `fullmove_number`, `halfmove_clock`, `ply()`,
  `fen()`.
- Pieces: `piece_type_at`, `color_at`, `piece_at`, `king`, `squares_with`,
  `piece_count`, `has_piece`.
- Attack/defence: `attacks`, `attackers`, `is_attacked_by`.
- Game state: `is_check`, `is_checkmate`, `is_stalemate`,
  `is_insufficient_material`.
- Moves: `legal_moves`, `is_legal`, `is_capture`, `is_en_passant`,
  `is_castling`, `gives_check`, `moving_piece_type`.
- History (trajectory): `move_history`, `own_move_count`.

`CHESS` is a curated `SimpleNamespace`: color/piece-type/square constants and
**pure** helpers (`square`, `square_file`, `square_rank`, `square_name`,
`square_distance`, `parse_square`, …). It deliberately excludes `chess.engine`,
`chess.pgn`, `chess.polyglot`, `chess.syzygy`, `chess.svg`, and the `Board`
constructor. `scorer_globals()` returns the global namespace
(`chess`=CHESS, `piece`=name→type) to inject into generated scorers.

### Worker-boundary note

M4 runs scorers in a separate process. Whatever is exposed must be
reconstructable from serializable input. The wire format is **FEN + move
history (UCI) + own_color**; the worker rebuilds a `chess.Board`, wraps it in
`ReadOnlyBoard`, and everything crossing the boundary stays plain data.

## 7. M4 hardening checklist (the real security boundary)

- [x] Allowlist AST validator (fail closed) + close `str.format` hole +
      block leading-underscore attribute access.
- [ ] Run the scorer in a **separate process** (batch-per-move: one worker call
      scores all candidates for a move and returns the breakdowns — avoids
      per-call process-spawn cost).
- [ ] **Timeout** via process join + terminate.
- [ ] **Resource limits**: `resource.setrlimit(RLIMIT_AS, RLIMIT_CPU)` in the
      worker; drop network/FS access. Consider seccomp / a container
      (gVisor/Firecracker) for production.
- [x] Output clamping to `[-10, +10]`, non-finite → 0 (already in `loader.py`).
- [ ] **Sample-position validation**: before using a generated scorer in a
      game, run it on canned positions (start, queen hanging, mate threat,
      endgame, pawn-only, queenside-only); reject if it crashes, times out,
      returns non-numeric, is constant, or returns absurd values.
- [ ] **Neutral fallback**: on any generation/validation/execution failure,
      fall back to a zero scorer (pure engine play at target Elo) instead of
      hard-failing the game (plan §14). Currently `cli._build_scorer` hard-fails.

## 8. Migration plan (C is built but not yet wired in)

1. **Done:** allowlist validator; `ReadOnlyBoard` + `CHESS` namespace + tests.
   The live game still uses `SafeChessContext` and the hand-coded
   queen-obsessed scorer — nothing is broken.
2. **Next:** update the system prompt (`llm/prompt.py`) to teach the
   `ReadOnlyBoard` API instead of the old context; teach the new scorer
   signature to call `chess.*` helpers.
3. Build the M4 separate-process worker that reconstructs `ReadOnlyBoard` from
   FEN + history and runs the scorer batched-per-move, with timeout + rlimits.
4. Port the selector to call the worker; port (or re-derive) the
   queen-obsessed scorer against the new API for parity testing.
5. Add the neutral fallback + sample-position validation.
6. Once at parity, retire `SafeChessContext`.

## 9. Open questions for next session

- Exact precomputed scalars worth adding to the hybrid (king safety metric,
  pawn-structure features) — driven by `prompt_minds.md`.
- Whether to expose `Move`/`Piece` value objects (current choice) or flatten
  everything to ints/bools for an even smaller escape surface.
- Container vs. `setrlimit`-only for the first M4 cut (leaning `setrlimit` +
  process isolation for the MVP; container later).
