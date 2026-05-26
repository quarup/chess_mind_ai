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
- [x] Run the scorer in a **separate process** (batch-per-move: one worker call
      scores all candidates for a move and returns the triples). Implemented in
      `sandbox/worker.py` (`score_candidates_sandboxed`) + `selector.
      select_move_sandboxed`. Per-call interpreter spawn (~0.5s); a persistent
      worker pool is a later optimization.
- [x] **Wall-clock timeout** killing the worker's process group. Separate from
      the CPU rlimit below — `RLIMIT_CPU` does not fire on a blocking/sleeping
      loop, so the parent enforces a real wall-clock kill.
- [~] **Escape prevention (the primary defense):** on Linux the worker is
      wrapped in unprivileged `unshare --user --map-root-user --net --mount`
      namespaces (drops network, isolates mount/user view). **seccomp-bpf is
      still TODO** — no Python binding is installed in the target environments
      yet; it's the highest-value remaining hardening. The macOS Seatbelt
      backend is also TODO (currently macOS runs in "reduced isolation").
- [x] **Resource limits:** `resource.setrlimit` for `RLIMIT_AS` (memory),
      `RLIMIT_CPU`, and `RLIMIT_FSIZE=0` (no file writes), applied in the worker
      before untrusted code runs. These bound *resource exhaustion*; they do
      **not** prevent escape (that's seccomp/namespaces above). cgroup caps TODO.
- [x] Output clamping to `[-10, +10]`, non-finite → 0 (already in `loader.py`).
- [ ] **Sample-position validation**: before using a generated scorer in a
      game, run it on canned positions (start, queen hanging, mate threat,
      endgame, pawn-only, queenside-only); reject if it crashes, times out,
      returns non-numeric, is constant, or returns absurd values.
- [x] **Neutral fallback**: on any sandbox failure (validation, timeout,
      resource limit, crash, malformed output) `select_move_sandboxed` falls
      back to an all-zero style score — pure engine play at the target Elo —
      instead of aborting the game (plan §14). The CLI routes LLM-generated
      source through the sandbox; the trusted hand-coded scorer stays
      in-process.

## 8. Migration plan (C is built but not yet wired in)

1. **Done:** allowlist validator; `ReadOnlyBoard` + `CHESS` namespace + tests.
2. **Done:** M4 separate-process worker (`sandbox/worker.py`) + sandboxed
   selector + neutral fallback. The CLI runs LLM-generated source in the
   sandbox.
3. **Done:** the system prompt (`llm/prompt.py`) now teaches the `ReadOnlyBoard`
   API + the curated `chess.*` namespace + the `piece(name)` helper, with a
   worked queen-obsessed example.
4. **Done:** the worker reconstructs `ReadOnlyBoard` (not `SafeChessContext`):
   `_score_request` builds the before-position view and uses `ctx.peek(move)`
   for the after-position; `load_scorer` injects `scorer_globals()` (`chess` +
   `piece`) into the exec namespace. A `peek(move)` method was added to
   `ReadOnlyBoard` so `action_score` can inspect the resulting position (e.g.
   hang/trade checks) without a mutable board. The queen-obsessed scorer is
   ported to the new API as an inline parity reference in `tests/test_worker.py`
   (sandboxed port picks the same move as the in-process `SafeChessContext`
   scorer it mirrors).
5. **Next:** add sample-position validation (run a new scorer on canned
   positions before first use; regenerate or fall back if it misbehaves).
6. Once fully at parity, retire `SafeChessContext`. **Not yet done:**
   `SafeChessContext` still backs the in-process default `./play` path
   (`select_move` + the hand-coded `queen_obsessed` scorer). Retiring it needs
   an explicit decision (moving that path onto `ReadOnlyBoard` too).

## 9. Open questions for next session

- Exact precomputed scalars worth adding to the hybrid (king safety metric,
  pawn-structure features) — driven by `prompt_minds.md`.
- Whether to expose `Move`/`Piece` value objects (current choice) or flatten
  everything to ints/bools for an even smaller escape surface.
- ~~Container vs. `setrlimit`-only for the first M4 cut~~ — **decided, see §11**:
  a layered worker (portable core + pluggable OS backend).

## 10. Prior art — how others sandbox generated code (2026-05 research)

Research into how others run untrusted/LLM-generated code (full digest in the
session that produced this doc). The headline: **our chosen direction matches
the consensus**, and we should sharpen M4 toward seccomp + namespaces rather
than leaning on resource limits.

### The load-bearing lesson: in-process Python sandboxing is broken by design
- **pysandbox** was retired by its author (Victor Stinner) with exactly that
  verdict — the trusted base is all of CPython, and introspection yields too
  many escapes (a public challenge found escapes within a day).
- **RestrictedPython** (Zope/Plone) explicitly states it "is not a sandbox" and
  has had real escapes (e.g. stack-frame access, GHSA-wqc8-x2pr-7jqh).
- ⇒ Strong, primary-grade confirmation that our **AST allowlist is hardening,
  not the boundary**. Put the boundary in the OS.

### The proportionate stack for a *pure function* like ours
seccomp-bpf (tight syscall allowlist) + empty network namespace + no filesystem
(Landlock / mount namespace) + setrlimit/cgroup CPU+memory caps + an external
wall-clock watchdog. `bubblewrap`/`nsjail` or Anthropic's open-source
`@anthropic-ai/sandbox-runtime` can assemble most of it with little code.
Heavier options (gVisor, Firecracker microVMs, WASM/Wasmtime+WASI with all
capabilities denied) are stronger but overkill for one float-returning function
— reserve them for higher volume / multi-tenant later.

### Reference architectures
- OpenAI Code Interpreter → **gVisor**. Modal → gVisor. E2B → **Firecracker**
  microVMs. Anthropic Claude Code → macOS Seatbelt / Linux **bubblewrap** +
  domain-allowlisting network proxy. Open Interpreter's own docs: "no local
  python sandbox can ever be completely secure" → isolate the process.

### OpenClaw specifically — mostly *not* applicable to us
OpenClaw (Peter Steinberger's self-hosted AI assistant / agent gateway, formerly
Clawdbot → Moltbot, ~late-2025/early-2026) is an **autonomous agent** framework.
Its security work — the **PRISM** runtime shield (prompt-injection scanning,
DLP, lifecycle hooks), **exec approvals / human-in-the-loop**, and Docker
isolation of agent tool calls — targets agent threats we don't have. Only the
"isolate untrusted execution in a separate container/process" idea maps to us,
and that's already our M4 plan.

The widely-cited claim *"a sandbox alone can't stop data exfiltration / agent
manipulation"* is **true for agents** (their control flow is steered by
attacker-influenced text, and they leak through authorized channels) but **does
not apply to our pure scorer**: no tool loop, no untrusted text steering
behavior, no authorized exfiltration channel, no "instructions" to rewrite. For
us the sandbox *is* essentially the whole game, because the function should have
zero capabilities.

> **Verification caveat:** OpenClaw is well-corroborated as a real project
> (GitHub repo, Wikipedia, press), but its primary security sources
> (`docs.openclaw.ai`, arXiv:2603.11853) returned HTTP 403 to automated fetch,
> so PRISM specifics are from secondary snippets. Since none of it applies to
> our threat model, re-verification is low priority.

## 11. Sandbox runtime & platform plan (M4 — decided 2026-05)

### 11.1 Requirement

The sandbox must run in **two** environments:

- **macOS** — the local dev machine ("at least works on my Mac").
- **The Claude Code cloud container** (referred to in conversation as "the
  Anthropic VM") — a Linux container, so the sandbox can be exercised and
  validated during web/cloud sessions.

So cross-platform (macOS + Linux) is a hard requirement; Windows is not a
target.

### 11.2 What the cloud container actually allows (probed 2026-05)

- Linux 6.18 x86_64, running inside a container (cgroups present).
- **Unprivileged user + network namespaces work** — `unshare --user
  --map-root-user --net` succeeds → we can drop network and isolate FS/PID
  without root.
- `unshare` is present; **`bwrap` / `firejail` / `nsjail` / `wasmtime` are NOT
  installed**, and we don't assume the ability to install system packages.
- `resource.setrlimit(RLIMIT_AS, RLIMIT_CPU)` is available (also on macOS).
- No `seccomp` Python binding (adding one needs a compiler + network).

### 11.3 Sandbox-mechanism availability by platform

Background on each mechanism is in §10; this is just *what runs where*.

| Mechanism | macOS | Cloud container (Linux) | Notes |
|---|---|---|---|
| separate process + `setrlimit` | ✅ | ✅ | portable, no root |
| wall-clock watchdog kill | ✅ | ✅ | needed *separately* from `RLIMIT_CPU` |
| user/net/mount/pid namespaces (`unshare`) | ❌ | ✅ unprivileged | Linux-only |
| seccomp-bpf syscall allowlist | ❌ | ⚠️ no binding installed | Linux-only |
| Seatbelt (`sandbox-exec`) | ✅ (deprecated API) | ❌ | macOS-only |
| bubblewrap / nsjail / firejail | ❌ | ❌ not installed | — |
| WASM (Wasmtime / Pyodide) | needs install | not installed | only *uniform* option |

**Takeaway:** no single strong-isolation mechanism is available on both
platforms out of the box. seccomp is Linux-only; Seatbelt is macOS-only; WASM is
uniform but not installed and heavy to integrate (and fights option C — 11.6).
For how these mechanisms relate conceptually (visibility vs syscall surface),
see §12.4.

### 11.4 Decision: layered worker with a pluggable OS-isolation backend

**Portable core** (identical on macOS + cloud container; no deps, no root):

- run the scorer in a **separate worker process** (batch-per-move);
- `setrlimit`: `RLIMIT_AS` (address space / memory), `RLIMIT_CPU` (CPU
  seconds), `RLIMIT_FSIZE` (cap/zero file writes), and best-effort
  `RLIMIT_NPROC`;
- an external **wall-clock watchdog** that kills the worker — this is separate
  from `RLIMIT_CPU`, which does **not** fire on a blocking/sleeping loop;
- scrub the environment, set cwd to a temp dir, close inherited fds;
- existing layers carry over: AST allowlist validator, restricted builtins,
  output clamp, and a **neutral fallback** (never hard-fail the game).

Because generated code can't `import` anything (AST layer), it already cannot
open sockets or files at the Python level; the OS layer below is
defense-in-depth for the case where that layer is bypassed.

**Pluggable OS backend, selected at runtime:**

- **Linux** (cloud container + production): launch the worker under `unshare
  --user --map-root-user --net --mount --pid` to drop network and isolate
  FS/PID. Confirmed runnable in the cloud container.
- **macOS**: a Seatbelt profile via `sandbox-exec` denying filesystem + network
  (deprecated API, still functional).
- **Fallback**: if no backend is available, run the portable core + AST layer
  and log **"reduced isolation"** — degrade, never crash.

**Implementation gotchas to remember:**

- Results must return to the parent over an **OS pipe**, not a regular file —
  `RLIMIT_FSIZE` caps file writes but does not affect pipes, so IPC keeps
  working. (Avoid `multiprocessing.Queue` if it might spill to a temp file;
  prefer an explicit `os.pipe`.)
- `RLIMIT_NPROC` is **per-user**, not per-process, so lowering it can affect
  sibling processes sharing the uid in a container — treat it as best-effort;
  prefer the PID namespace / seccomp to block `fork`/`execve`.

### 11.5 Validation

Tests run the worker in both environments. The **Linux namespace backend is
exercisable in the cloud container**, so web/cloud sessions validate the real
Linux-isolation path every run; the macOS Seatbelt path is validated locally.
Target test assertions: the worker (a) returns correct scores, (b) is killed on
a wall-clock timeout, (c) is killed / errors on a memory blowup, (d) denies a
deliberate escape attempt when a backend is active, (e) falls back neutrally on
any failure.

### 11.6 Why not WASM now

WASM (Wasmtime + Pyodide / CPython-WASI) is the only mechanism identical across
macOS / Linux / Windows and capability-deny-by-default (§10). Deferred because:
it isn't installed here; it's heavy to integrate (Pyodide image size, startup
cost); and it fights option C — to keep the live `ReadOnlyBoard` (python-chess)
inside the module we'd have to ship python-chess into WASM or precompute board
facts into plain data, restructuring the context boundary. Documented as the
upgrade if we ever need one uniform, strong, write-once sandbox.

### 11.7 Caveats

The no-root, no-install options (setrlimit, namespaces, Seatbelt) are **not
kernel-bug-proof** the way gVisor / Firecracker microVMs are: untrusted code
still runs as native code on the host kernel, reachable through the allowed
syscalls. For our threat model — buggy or escape-attempting *pure* code,
single-user, low volume — this is proportionate. Upgrade paths if the threat
model grows: add a seccomp binding, or move to gVisor, Firecracker, or WASM.

## 12. Runtime architecture (as built)

### 12.1 Process topology & trust boundary

```
┌─ MAIN PROCESS (trusted) ─────────────────────────────────┐
│  CLI · Stockfish wrapper (engine.py) · LLM call (Gemini)  │
│  selector: Elo budget + style_weight + noise + pick move  │
│  AST validation · hand-coded queen_obsessed scorer        │
│  score_candidates_sandboxed()  ── spawns ──┐              │
└────────────────────────────────────────────┼────────────┘
              JSON request (stdin) │          │  JSON response (stdout)
              source, root FEN,    ▼          │  [(action,state,traj), …]
              UCI history, own_color,         │  or {"ok": false}
              candidates, mem/cpu limits      │
┌─ WORKER PROCESS (untrusted) ─────────────── ▼ ───────────┐
│  [optional prefix: `unshare …` (Linux) / Seatbelt (mac)]  │
│  _apply_resource_limits()  → setrlimit AS / CPU / FSIZE   │
│  load_scorer(source) → AST allowlist + restricted builtins│
│  rebuild board from FEN+history → ReadOnlyBoard           │
│  run generated action/state/trajectory(ctx, move)  ◄─ the │
│  return triples                         ONLY untrusted    │
└─────────────────────────────────────────  code ──────────┘
```

The **only untrusted code is the LLM-generated scorer source**; everything else
runs in the trusted main process. The worker is a freshly `exec`'d interpreter
(`python -m chess_mind_ai.sandbox.worker`) — **not** a `fork` — with a scrubbed
environment (no API keys), its own process group (`start_new_session=True`, so
the parent can kill the whole group on timeout), communicating only over pipes.
Generated code is never loaded or `exec`'d in the main process. It is spawned
fresh per move (batch-per-move: all candidates scored in one worker call); a
persistent worker pool is a later optimization.

### 12.2 Data flow of one prompt-driven AI move

1. **Main**: `engine.top_candidates(board)` → Stockfish returns top-N moves +
   centipawn scores.
2. **Main**: `select_move_sandboxed` validates the source (fail-fast),
   serializes the request, and spawns the worker.
3. **Worker**: applies `setrlimit` to itself → `load_scorer` (validator +
   restricted builtins + output clamp) → rebuilds the board → runs the
   generated functions per candidate → returns triples (**numbers only**).
4. **Main**: receives triples, or `None` on any failure → neutral all-zero
   style; then `cp + style_weight·style + noise`, Elo-budget filter, pick max.

Untrusted code only ever produces a style number per candidate; engine
evaluation, move legality, and the final selection are all trusted.

### 12.3 Defense layers around the untrusted code

1. AST allowlist validator (parent fail-fast **and** worker via `load_scorer`).
2. Restricted builtins + output clamping (worker).
3. Separate process (memory/state isolation from the parent).
4. `setrlimit` — `RLIMIT_AS` / `RLIMIT_CPU` / `RLIMIT_FSIZE=0` (worker).
5. Wall-clock timeout + process-group kill (parent).
6. OS-isolation backend wrapping the worker: `unshare` namespaces (Linux, now);
   seccomp + macOS Seatbelt (TODO).

### 12.4 How the OS backends relate: unshare vs seccomp vs Seatbelt

These act on **different axes** and *compose*; they are not interchangeable:

- **`unshare` (Linux namespaces)** changes **what the process can SEE / what
  resources exist** for it. `--net` gives an empty network namespace (only a
  down `lo`) — the process *can still call* `socket()`, there's just no network
  to reach; `--mount` isolates the mount view; `--user --map-root-user` confines
  "root" to the namespace and is what makes the others creatable unprivileged.
  This is **resource visibility**, not syscall restriction.
- **`seccomp` (Linux)** restricts **which syscalls may be invoked at all**,
  shrinking the reachable kernel attack surface (forbid `socket`, `openat`,
  `execve`, `ptrace`, … and allow only the handful a pure scorer needs). It is
  **orthogonal** to namespaces: `unshare` removes the *things*, seccomp removes
  the *operations*. Stacked, you get "no network exists **and** `socket()` is
  uncallable **and** the syscall surface is minimal."
- **Seatbelt (macOS)** is a **single policy mechanism covering both axes at
  once**, because macOS has neither namespaces nor seccomp. One SBPL profile
  (via `sandbox-exec` / `sandbox_init`) denies file/network/exec operations.

So the OS layer is: **Linux = `unshare` + seccomp stacked** (we have `unshare`;
seccomp is TODO); **macOS = a single Seatbelt profile** (TODO). The portable
core (separate process + `setrlimit` + wall-clock timeout) underlies all of
them, and if no backend is available the worker still runs under the portable
core + AST layer ("reduced isolation").
