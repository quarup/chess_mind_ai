# ChessMind AI — Implementation Plan

## Project Identity

**Name:** ChessMind AI

**Concept:** A prompt-configurable, conversational chess AI that can emulate different playing styles, personalities, and difficulty levels.

**Long-term vision:** ChessMind AI should eventually support voice, sound, and conversational interaction, allowing users to describe the kind of opponent they want and then play, talk, and iterate with that AI opponent naturally.


## 0. Project Goal

Build **ChessMind AI**, a chess AI that can be configured with natural-language prompts such as:

- "Aggressively use your queen from the start."
- "Play very defensively."
- "Try to only use your pawns to win the game."
- "Try to rush toward a winning endgame."
- "Only play on the queenside if possible."
- "Be obsessed with queen captures and checks."

The AI should also support a target difficulty, preferably expressed as an approximate chess rating / Elo.

The core idea is **not** to train a full chess model from scratch at first. Instead, use a strong existing chess engine for legality and objective move quality, and add a prompt-generated style scoring layer that influences move selection.

---

## 1. Core Architecture

```text
User prompt + target Elo
        ↓
LLM generates style scorer code
        ↓
Validate and sandbox generated scorer
        ↓
Chess engine generates candidate moves / candidate lines
        ↓
Generated scorer evaluates actions, states, and trajectories
        ↓
Objective engine score + style score + rating noise
        ↓
Choose final move
        ↓
Expose as UCI engine / local app / Lichess bot
```

The chess engine remains responsible for:

- Legal moves
- Objective evaluation
- Tactical safety
- Candidate move generation

The generated scorer is responsible for:

- Style preference
- Prompt-specific behavior
- Action-level bias
- State-level bias
- Trajectory-level bias

---

## 2. Recommended MVP Stack

Use:

- Python
- `python-chess`
- Stockfish
- Optional later: Lc0 or Maia
- LLM for prompt-to-scorer generation
- Local sandbox worker for generated scorer execution
- UCI wrapper so the bot can plug into existing chess tools

Recommended external tools:

- `cutechess-cli` for AI-vs-AI testing
- Arena or Cute Chess GUI for local play
- Lichess bot bridge for online deployment later

---

## 3. Key Design Principle

Do **not** let the LLM choose chess moves directly.

Instead:

```text
Bad:
LLM → "I think Qh5 is a good move"

Good:
Chess engine → candidate legal moves
Generated style scorer → preference over candidates
Move selector → final move
```

The LLM is used to generate a scoring function, not to calculate chess tactics.

---

## 4. Scoring Model

Use a combination of:

```text
total_score =
    objective_engine_score
  + style_weight * style_score
  + rating_noise
```

Where:

```text
style_score =
    action_score
  + state_score
  + trajectory_score
```

**Chosen default in M2:** `style_weight = 30`. With style components empirically
in the [-10, +10] range, one "style unit" is worth ~30cp — enough that the
queen-obsessed bot can justify a 60-90cp engine deficit to play a strong queen
move, while still being filtered out at high Elo where the blunder budget
tightens to 50cp.

### 4.1 Objective Engine Score

Provided by Stockfish, usually in centipawns or mate scores.

This keeps the AI from making absurd moves unless the target Elo allows large mistakes.

### 4.2 Action Score

Scores the move itself.

Examples:

- Did the queen move?
- Was the move a queen capture?
- Was the move a check?
- Did the move stay on the queenside?
- Was a pawn moved?
- Was a knight avoided?
- Did the move sacrifice material?

This is important because two moves can lead to similar board states but differ stylistically.

Example:

```text
Queen-obsessed bot:
- Qxd5 should score higher than Bxd5 if both are legal and similarly strong.
```

### 4.3 State Score

Scores the resulting board position.

Examples:

- Is the queen more mobile?
- Is the king safer?
- Are pieces concentrated on one side of the board?
- Are there fewer pieces on the board?
- Is the bishop pair preserved?
- Are pawns advanced?
- Is a file open?

This lets the bot reward moves that prepare a style goal even if the move does not directly perform the style.

Example:

```text
Queen-activity bot:
- e4 may score well because it opens the queen's diagonal.
```

### 4.4 Trajectory Score

Scores the sequence of moves so far.

Examples:

- Queen moved many times in the opening.
- The bot avoided moving knights.
- The bot only used pawns when possible.
- The bot repeatedly gave checks.
- The bot avoided trades for 20 moves.
- The bot rushed into an endgame.

This captures styles that depend on history, not just the current move or position.

---

## 5. Prompt-to-Code Strategy

Instead of converting the user prompt into a fixed JSON vector such as:

```json
{
  "queen_activity": 0.8,
  "king_safety": 0.2
}
```

generate scorer code directly.

**LLM provider strategy (M3):** scorer generation goes through a thin
`StyleScorerLLM` protocol so we can swap providers without touching the rest
of the pipeline. Concrete adapters for **Google Gemini**, **Anthropic**, and
**OpenAI** all conform to the same interface. The default is **Gemini 2.5
Flash-Lite** on Google's free tier so the bot is playable without a credit
card; Anthropic and OpenAI are drop-in alternatives selectable via config.

See [`docs/llm-providers.md`](docs/llm-providers.md) for the full pricing
comparison and the reasoning behind these choices.

The LLM should output Python functions with this interface:

```python
def action_score(ctx, move) -> float:
    return 0.0

def state_score(ctx) -> float:
    return 0.0

def trajectory_score(ctx) -> float:
    return 0.0
```

Example generated scorer for a queen-obsessed bot:

```python
def action_score(ctx, move):
    score = 0.0

    if ctx.moving_piece_is(move, "queen"):
        score += 1.2

        if ctx.is_capture(move):
            score += 0.9

        if ctx.gives_check(move):
            score += 0.8

        if ctx.destination_near_enemy_king(move):
            score += 0.5

    if ctx.causes_trade_of_piece(move, "queen"):
        score -= 2.5

    if ctx.hangs_piece_after_move(move, "queen"):
        score -= 2.0

    return score


def state_score(ctx):
    score = 0.0

    score += 0.7 * ctx.piece_mobility("queen")
    score += 0.8 * ctx.piece_attack_pressure("queen")
    score += 0.5 * ctx.piece_centralization("queen")
    score -= 1.2 * ctx.piece_under_attack("queen")

    return score


def trajectory_score(ctx):
    score = 0.0

    queen_moves = ctx.count_own_moves_by_piece("queen")
    score += min(queen_moves, 5) * 0.3

    if ctx.own_queen_was_traded():
        score -= 5.0

    return score
```

---

## 6. Safety Model for Generated Code

Do **not** run generated code directly in the main app process.

Use layered restrictions:

```text
Generated scorer code
  ↓
Static AST validation
  ↓
Restricted Python globals/builtins
  ↓
Separate worker process
  ↓
Timeout and memory limits
  ↓
Optional Docker/gVisor/Firecracker sandbox
  ↓
Fallback if anything fails
```

### 6.1 Static AST Validation

Reject:

- Imports
- File access
- `eval`
- `exec`
- `compile`
- `open`
- `__import__`
- `globals`
- `locals`
- `vars`
- `getattr`
- `setattr`
- classes
- decorators
- async code
- lambdas
- suspicious dunder attributes

Example validator:

```python
import ast

ALLOWED_FUNCTION_NAMES = {
    "action_score",
    "state_score",
    "trajectory_score",
}

BANNED_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.With,
    ast.AsyncWith,
    ast.Lambda,
    ast.ClassDef,
    ast.Global,
    ast.Nonlocal,
    ast.Try,
    ast.Raise,
    ast.Delete,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
)

BANNED_CALL_NAMES = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "memoryview",
    "breakpoint",
}

BANNED_ATTRIBUTE_NAMES = {
    "__class__",
    "__bases__",
    "__subclasses__",
    "__globals__",
    "__code__",
    "__closure__",
    "__dict__",
    "__mro__",
    "__getattribute__",
}


class SafetyValidator(ast.NodeVisitor):
    def visit(self, node):
        if isinstance(node, BANNED_NODES):
            raise ValueError(f"Banned syntax: {type(node).__name__}")
        return super().visit(node)

    def visit_FunctionDef(self, node):
        if node.name not in ALLOWED_FUNCTION_NAMES:
            raise ValueError(f"Unexpected function: {node.name}")

        if node.decorator_list:
            raise ValueError("Decorators are not allowed")

        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALL_NAMES:
                raise ValueError(f"Banned call: {node.func.id}")

        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr in BANNED_ATTRIBUTE_NAMES:
            raise ValueError(f"Banned attribute: {node.attr}")

        self.generic_visit(node)


def validate_generated_code(source: str) -> ast.Module:
    tree = ast.parse(source, mode="exec")
    SafetyValidator().visit(tree)
    return tree
```

### 6.2 Restricted Builtins

Only expose safe builtins:

```python
SAFE_BUILTINS = {
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "range": range,
    "float": float,
    "int": int,
    "bool": bool,
    "round": round,
}

def load_scorer(source: str):
    tree = validate_generated_code(source)
    code = compile(tree, filename="<generated_scorer>", mode="exec")

    namespace = {
        "__builtins__": SAFE_BUILTINS,
    }

    exec(code, namespace, namespace)

    return {
        "action_score": namespace.get("action_score"),
        "state_score": namespace.get("state_score"),
        "trajectory_score": namespace.get("trajectory_score"),
    }
```

### 6.3 Separate Worker Process

Generated code should run outside the main app.

Use a process-level timeout:

```python
import multiprocessing as mp
import queue


def scorer_worker(source, request, result_queue):
    try:
        scorer = load_scorer(source)

        ctx = request["ctx"]
        move = request["move"]

        result = {
            "action_score": float(scorer["action_score"](ctx, move)),
            "state_score": float(scorer["state_score"](ctx)),
            "trajectory_score": float(scorer["trajectory_score"](ctx)),
        }

        result_queue.put({"ok": True, "result": result})

    except Exception as e:
        result_queue.put({"ok": False, "error": str(e)})


def run_scorer_with_timeout(source, request, timeout_seconds=0.05):
    result_queue = mp.Queue()

    process = mp.Process(
        target=scorer_worker,
        args=(source, request, result_queue),
    )

    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join()
        return {"ok": False, "error": "Scorer timed out"}

    try:
        return result_queue.get_nowait()
    except queue.Empty:
        return {"ok": False, "error": "No result returned"}
```

For performance, later use a persistent worker pool rather than creating a new process per scoring call.

### 6.4 OS / Container Restrictions

For production, run scorer workers inside containers or microVMs.

Example Docker flags:

```bash
docker run \
  --rm \
  --network none \
  --read-only \
  --pids-limit 64 \
  --memory 128m \
  --cpus 0.25 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user 1000:1000 \
  scorer-sandbox
```

Recommended restrictions:

- No network
- No mounted secrets
- Non-root user
- Read-only filesystem
- CPU limit
- Memory limit
- PID limit
- Dropped Linux capabilities
- Short execution timeout

---

## 7. Safe Chess Context API

The generated code should not receive raw engine objects, database handles, or file access.

Expose a narrow read-only context object:

```python
class SafeChessContext:
    def moving_piece_is(self, move, piece_name: str) -> bool:
        ...

    def is_capture(self, move) -> bool:
        ...

    def gives_check(self, move) -> bool:
        ...

    def destination_file(self, move) -> str:
        ...

    def source_file(self, move) -> str:
        ...

    def destination_near_enemy_king(self, move) -> bool:
        ...

    def causes_trade_of_piece(self, move, piece_name: str) -> bool:
        ...

    def hangs_piece_after_move(self, move, piece_name: str) -> bool:
        ...

    def piece_mobility(self, piece_name: str) -> float:
        ...

    def piece_attack_pressure(self, piece_name: str) -> float:
        ...

    def piece_centralization(self, piece_name: str) -> float:
        ...

    def piece_under_attack(self, piece_name: str) -> float:
        ...

    def count_own_moves_by_piece(self, piece_name: str) -> int:
        ...

    def own_queen_was_traded(self) -> bool:
        ...

    def king_safety(self) -> float:
        ...

    def material_balance(self) -> float:
        ...

    def fraction_of_own_pieces_on_files(self, files: list[str]) -> float:
        ...

    def control_of_files(self, files: list[str]) -> float:
        ...
```

Do not expose:

- Raw filesystem
- Environment variables
- Subprocess
- Network
- Full engine process
- Full Python objects with unsafe methods
- Database connections
- User credentials

---

## 8. Output Validation

Generated scorer outputs must be:

- Numeric
- Finite
- Clamped to a safe range

Example:

```python
import math

def clamp_score(value, low=-10.0, high=10.0):
    try:
        value = float(value)
    except Exception:
        return 0.0

    if not math.isfinite(value):
        return 0.0

    return max(low, min(high, value))
```

Never allow a generated scorer to return huge values that fully override the chess engine.

---

## 9. Difficulty / Elo Control

Difficulty should control how much the style is allowed to override the engine.

Use a centipawn budget:

```text
Target Elo 2200:
  style can choose among moves within ~50 cp of best

Target Elo 1800:
  style can choose among moves within ~120 cp of best

Target Elo 1400:
  style can choose among moves within ~250 cp of best

Target Elo 1000:
  style can choose among moves within ~500 cp of best

Target Elo 700:
  style can choose among moves within ~800+ cp of best
```

Selection process:

```python
candidate_lines = search_candidate_lines(board)

best_engine_score = max(line.engine_score for line in candidate_lines)

allowed_lines = [
    line for line in candidate_lines
    if line.engine_score >= best_engine_score - elo_blunder_budget(target_elo)
]

chosen = max(
    allowed_lines,
    key=lambda line: (
        line.engine_score
        + style_weight * line.style_score
        + rating_noise(target_elo)
    )
)
```

Add controlled randomness at lower ratings.

---

## 10. Search Strategy

### MVP

Use Stockfish MultiPV to get top-N moves.

```text
1. Ask Stockfish for top candidate_count(elo) candidate moves.
2. Apply each candidate move.
3. Evaluate style action score.
4. Evaluate style state score.
5. Combine with engine score.
6. Choose move.
```

**Chosen scaling formula in M2** (`elo.candidate_count`):

```python
multipv = max(5, min(40, int(50 - elo / 100)))
```

| Elo  | Candidates |
|-----:|-----------:|
| 700  | 40 (clamp) |
| 1000 | 40 (clamp) |
| 1500 | 35         |
| 2000 | 30         |
| 2200 | 28         |
| 3000 | 20         |
| ≥4500 | 5 (clamp) |

Reasoning: low-Elo bots want lots of candidates so style can promote moves the
engine would never suggest (e.g. early queen sorties). At high Elo we shrink
the candidate set — the Elo blunder budget would filter most of them out
anyway, and a smaller MultiPV lets Stockfish search each line more deeply
within the same time budget.

This is simpler but only shallow.

### Improved Version

Search candidate lines several plies deep.

```text
1. Generate candidate moves.
2. For each candidate, explore likely continuations.
3. Score:
   - objective engine value of final position
   - action scores across own moves
   - state score of final or intermediate positions
   - trajectory score over the whole line
4. Select first move from best line.
```

Conceptual code:

```python
def line_score(line, scorer):
    score = 0.0

    score += line.engine_score

    for position, move in line.own_moves:
        ctx = SafeChessContext(position, line.history)
        score += scorer.action_score(ctx, move)

    final_ctx = SafeChessContext(line.final_position, line.history)
    score += scorer.state_score(final_ctx)
    score += scorer.trajectory_score(final_ctx)

    return score
```

---

## 11. Testing Plan

### 11.1 Unit Tests

Test:

- Prompt-to-code output format
- AST validator
- Restricted builtins
- Safe context methods
- Timeout behavior
- Score clamping
- Fallback behavior
- Engine candidate generation

### 11.2 Generated Scorer Tests

Before using a generated scorer in a game, run it on sample positions:

- Starting position
- Queen capture available
- Queen hanging
- Checkmate threat
- Endgame position
- Pawn-only scenario
- Queenside-only scenario

Reject or regenerate if:

- It crashes
- It times out
- It returns non-numeric values
- It always returns the same score
- It gives absurd values
- It tries banned operations
- It references unavailable context methods

### 11.3 Chess Evaluation Tests

Run AI-vs-AI matches using `cutechess-cli`.

Test:

- Same prompt at different Elo levels
- Different prompts at same Elo
- Style adherence
- Blunder frequency
- Illegal move prevention
- Time control performance

---

## 12. MVP Milestones

### Milestone 1: Basic Chess Engine Wrapper **[done]**

- Install `python-chess`
- Connect to Stockfish
- Generate legal moves
- Get Stockfish best move
- Get MultiPV candidate moves
- Play a complete legal game

Shipped as `src/chess_mind_ai/engine.py`. Stockfish is invoked via
`python-chess`'s UCI engine helper.

### Milestone 2: Static Style Scorer **[done]**

- Implement hand-written scorer functions
- Score action/state/trajectory
- Combine with engine score
- Add Elo-based candidate filtering

Shipped as `src/chess_mind_ai/{context,scorers/queen_obsessed,selector,elo,cli}.py`.
The terminal CLI (`./play --color white --elo 1500 --explain`) drives a full
game against the queen-obsessed bot. Tunable defaults that landed in this
milestone:

- `style_weight = 30` (see section 4)
- `candidate_count(elo) = max(5, min(40, int(50 - elo / 100)))` (see section 10)

### Milestone 3: Prompt-to-Code Scorer

- Write LLM prompt that generates scorer code
- Require exact function interface
- Parse and validate generated code
- Run scorer locally with restricted builtins
- Add fallback scorer

### Milestone 4: Sandboxed Scorer Worker

- Move generated code execution into a separate process
- Add timeout
- Add memory/CPU limits
- Add output clamping
- Add sample-position validation

### Milestone 5: UCI Engine Interface

- Make the bot speak UCI
- Load prompt and Elo from config
- Test in Cute Chess or Arena

### Milestone 6: AI-vs-AI Evaluation

- Run prompt-vs-prompt matches
- Use `cutechess-cli`
- Save PGNs
- Calculate win rates and style metrics

### Milestone 7: Optional Web App

- React chessboard frontend
- Backend game session manager
- Prompt textbox
- Elo slider
- AI-vs-human and AI-vs-AI modes

### Milestone 8: Optional Lichess Bot

- Wrap UCI engine with a Lichess bot bridge
- Follow Lichess bot rules
- Only use bot accounts
- Do not assist human accounts during games

---

## 13. Example LLM Prompt for Scorer Generation

Use a system prompt like:

```text
You generate Python scoring code for a chess style engine.

You must output only valid Python code.

The code must define exactly these functions:
- action_score(ctx, move)
- state_score(ctx)
- trajectory_score(ctx)

Do not import anything.
Do not use open, eval, exec, compile, globals, locals, vars, getattr, setattr, dir, input, or any dunder attributes.
Do not define classes.
Do not use decorators.
Do not mutate ctx or move.
Return numeric scores only.

You may call only methods available on ctx.

The scorer should reflect the user's requested chess style.
Scores should usually be between -5 and +5.
Use positive scores for behavior matching the style.
Use negative scores for behavior violating the style.
```

Then user prompt:

```text
User style:
"Play like a queen-obsessed maniac. Move the queen early, capture with the queen when possible, avoid queen trades, and give queen checks whenever possible."
```

Expected output:

```python
def action_score(ctx, move):
    score = 0.0
    if ctx.moving_piece_is(move, "queen"):
        score += 1.2
        if ctx.is_capture(move):
            score += 0.9
        if ctx.gives_check(move):
            score += 0.8
        if ctx.destination_near_enemy_king(move):
            score += 0.4
    if ctx.causes_trade_of_piece(move, "queen"):
        score -= 2.5
    if ctx.hangs_piece_after_move(move, "queen"):
        score -= 2.0
    return score


def state_score(ctx):
    score = 0.0
    score += 0.7 * ctx.piece_mobility("queen")
    score += 0.8 * ctx.piece_attack_pressure("queen")
    score += 0.5 * ctx.piece_centralization("queen")
    score -= 1.2 * ctx.piece_under_attack("queen")
    return score


def trajectory_score(ctx):
    score = 0.0
    queen_moves = ctx.count_own_moves_by_piece("queen")
    score += min(queen_moves, 5) * 0.3
    if ctx.own_queen_was_traded():
        score -= 5.0
    return score
```

---

## 14. Important Product Constraints

### Do Not Promise Perfect Prompt Following

Some prompts may be impossible or self-defeating.

Example:

```text
"Only move pawns and never lose."
```

The bot should treat most style instructions as **soft preferences**, not hard rules.

### Keep Chess Sanity

The engine should prevent catastrophic moves unless the selected rating allows them.

### Add Explainability

For debugging, log:

- Prompt
- Generated scorer code
- Candidate moves
- Engine score
- Action score
- State score
- Trajectory score
- Final selected move
- Reason rejected moves were not selected

This will make it much easier to debug prompt behavior.

### Always Have a Neutral Fallback

If scorer generation or sandbox execution fails, play normal engine moves.

---

## 15. Long-Term Improvements

### Human-Like Rating Models

Add Maia or another human-move prediction model to better emulate rating levels.

### Learned Style Evaluator

Collect data from user feedback:

```text
Prompt
Position
Candidate move
Was this move stylistically appropriate?
```

Train a model:

```text
style_score = model(position, move, prompt)
```

### Reinforcement Learning

Later, train prompt-conditioned agents through self-play.

This is expensive and should not be part of the MVP.

### DSL / AST Migration

If generated Python becomes hard to secure or debug, migrate from generated Python to a domain-specific scoring language.

The external user experience remains the same:

```text
Natural language prompt → chess style behavior
```

Only the internal implementation changes.

---

## 16. First Implementation Checklist

M1 + M2 status:

- [x] Create Python project.
- [x] Install `python-chess`.
- [x] Install Stockfish.
- [x] Write simple board loop.
- [x] Ask Stockfish for top-N moves using MultiPV.
- [x] Implement basic `SafeChessContext`.
- [x] Implement hard-coded `action_score`, `state_score`, `trajectory_score`.
- [x] Combine engine score and style score.
- [x] Add target Elo candidate filtering.
- [x] Run games locally.
- [ ] Add generated scorer interface.       *(M3)*
- [ ] Add AST validator.                    *(M3)*
- [ ] Add restricted builtins.              *(M3)*
- [ ] Add fallback scorer.                  *(M3)*
- [ ] Add subprocess timeout.               *(M4)*
- [ ] Add score clamping.                   *(M4)*
- [ ] Add UCI wrapper.                      *(M5)*
- [ ] Test with Cute Chess.                 *(M5)*
- [ ] Iterate on scoring quality.           *(ongoing)*

---

## 17. Summary

The recommended system for **ChessMind AI** is:

```text
ChessMind AI
  = existing chess engine
  + LLM-generated style scorer
  + sandboxed execution
  + action/state/trajectory scoring
  + Elo-based move quality budget
  + UCI-compatible wrapper
```

This avoids training a chess engine from scratch while still allowing very expressive prompt-driven behavior.
