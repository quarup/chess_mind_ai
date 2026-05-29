# Playing ChessMind AI in Cute Chess

This guide walks through installing [Cute Chess](https://cutechess.com/),
registering ChessMind AI as a UCI engine, and playing against it (human-vs-AI,
AI-vs-AI, or scripted tournaments via `cutechess-cli`).

The same UCI launcher (`./uci` at the repo root) works in any UCI-compatible
GUI; Cute Chess is documented here because it's free, cross-platform, ships a
matching CLI, and is the GUI we develop against.

---

## 1. Install Cute Chess

### macOS

Cute Chess does not ship a prebuilt macOS binary, so you build from source
once. The whole sequence takes ~10–15 minutes (mostly the Qt download).

```bash
# 1. Build dependencies (Qt6 is ~1.5 GB — go get a coffee).
brew install cmake qt6 qt5compat

# 2. Clone the v1.4.0 release.
mkdir -p ~/src && cd ~/src
git clone --depth 1 --branch v1.4.0 https://github.com/cutechess/cutechess.git
cd cutechess

# 3. Configure + build.
cmake -B build -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="$(brew --prefix qt6);$(brew --prefix qt5compat)"
cmake --build build -j$(sysctl -n hw.ncpu)

# 4. Put the two binaries somewhere on PATH.
mkdir -p ~/.local/bin
ln -sf ~/src/cutechess/build/cutechess     ~/.local/bin/cutechess
ln -sf ~/src/cutechess/build/cutechess-cli ~/.local/bin/cutechess-cli

# 5. (One-time) ensure ~/.local/bin is on your PATH.
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# 6. Sanity check.
cutechess-cli --version    # should print "cutechess-cli 1.4.0"
```

`cutechess` (the GUI) is then launched with `cutechess` from a terminal.

### Linux

Easiest path is the official AppImage from the
[releases page](https://github.com/cutechess/cutechess/releases). Download
`Cute_Chess-<version>-x86_64.AppImage`, `chmod +x`, and run it. `cutechess-cli`
is bundled separately as a build artifact — either build from source (recipe
above, just swap `brew --prefix qt6` for your distro's Qt6 install) or grab a
distro package if one exists.

### Windows

Download `cutechess-<version>-win64.exe` (installer) or the `.zip` portable
build from the [releases page](https://github.com/cutechess/cutechess/releases).
The `.exe` puts the GUI and `cutechess-cli.exe` next to each other; the rest
of this guide's paths translate directly — replace `/Users/.../uci` with the
full path to `uci.bat`, which you'll want to create alongside the existing
`./uci` script (a one-line `.bat` that runs `.venv\Scripts\chess-mind-ai-uci`
works).

---

## 2. Register ChessMind AI as an engine

Cute Chess stores its engine list in a single JSON file. You can either add
engines through the GUI (slow but foolproof) or write the file directly (fast
but path-dependent).

### Through the GUI (recommended first time)

1. Open Cute Chess.
2. **Cute Chess menu → Settings…** (or ⌘-,).
3. Click the **Engines** tab → **Add**.
4. Fill in:
   - **Name:** `ChessMind AI`
   - **Command:** `/absolute/path/to/chess_mind_ai/uci` (the launcher script,
     not the Python entry point — it handles the venv + the macOS
     editable-install workaround).
   - **Working directory:** `/absolute/path/to/chess_mind_ai`
   - **Protocol:** `UCI`
5. Click **OK** to save the engine.
6. Click **Add** again and register Stockfish too — typically
   `/opt/homebrew/bin/stockfish` on macOS, `/usr/games/stockfish` on Debian,
   or wherever your install put it. Working directory can stay blank.
7. **OK** to close Settings.

### Directly editing `engines.json`

The file lives at:

| Platform | Path |
| --- | --- |
| macOS   | `~/Library/Application Support/cutechess/Cute Chess/engines.json` |
| Linux   | `~/.local/share/cutechess/Cute Chess/engines.json` |
| Windows | `%APPDATA%\cutechess\Cute Chess\engines.json` |

A working entry for ChessMind AI looks like this — substitute your own
absolute paths in `command` and `workingDirectory`:

```json
[
    {
        "command": "/Users/you/chess_mind_ai/uci",
        "initStrings": [],
        "name": "ChessMind AI",
        "options": [
            {"name": "Prompt",            "type": "string", "default": "",    "value": ""},
            {"name": "UCI_Elo",           "type": "spin",   "default": 1500,  "value": 1500, "min": 400, "max": 4000},
            {"name": "UCI_LimitStrength", "type": "check",  "default": true,  "value": true},
            {"name": "Move Time",         "type": "spin",   "default": 1000,  "value": 1000, "min": 1,   "max": 600000}
        ],
        "protocol": "uci",
        "stderrFile": "",
        "variants": ["standard"],
        "whitePov": false,
        "workingDirectory": "/Users/you/chess_mind_ai"
    },
    {
        "command": "/opt/homebrew/bin/stockfish",
        "name": "Stockfish",
        "protocol": "uci",
        "variants": ["standard"]
    }
]
```

> **Heads up:** Cute Chess rewrites `engines.json` on quit. Edit the file with
> Cute Chess **closed**, or the GUI will overwrite your changes.

---

## 3. Play a game

**Game → New** (⌘-N) opens the New Game dialog.

- **White / Black:** pick **Human** for the side you want to play, and **CPU**
  for the side you want the engine to play. The dropdown under CPU lets you
  pick **ChessMind AI** or **Stockfish**.
- **Time Control:** click the button (it defaults to "40 moves in 5 min") and
  either uncheck the clock entirely, or pick **"Time per move"** with a few
  seconds. ChessMind AI ignores tournament-clock signals
  (`wtime`/`btime`) at M5 — see [Known limitations](#known-limitations) below
  — so generous time controls are kinder than tight ones.
- **OK** to start. Click your piece, then the destination square. The engine
  replies a beat later.

To watch ChessMind AI play itself or Stockfish, set both colors to **CPU** and
pick engines for each.

---

## 4. Configure a prompt-driven personality

By default the engine runs the hand-coded "queen-obsessed" scorer (free, no
API key needed). To swap in an LLM-generated scorer for a natural-language
style:

1. **Get a free Gemini API key** at <https://aistudio.google.com/apikey>.
2. **Export it in the terminal you launch Cute Chess from** — Cute Chess
   inherits the parent shell's environment, so it has to be set *before* you
   run `cutechess`:
   ```bash
   export GEMINI_API_KEY=your-key-here
   cutechess
   ```
   (Put `export GEMINI_API_KEY=…` in `~/.zshrc` if you want it permanent — see
   the project README for tradeoffs.)
3. In Cute Chess: **Settings → Engines → ChessMind AI → Configure** (or
   double-click the entry). Set the **Prompt** option to a style description,
   e.g. `play very defensively, never trade queens` or `keep moving the queen,
   give checks whenever possible`. **OK** to save.
4. **Game → New** — the engine will hit Gemini on `isready` (before the
   clock starts), validate the generated code through the AST allowlist, and
   use it for the whole game.

Clear the **Prompt** option (empty string) to fall back to the hand-coded
scorer.

---

## 5. Run engine matches with `cutechess-cli`

`cutechess-cli` is the headless tournament runner — useful for evaluating
prompts against each other, against Stockfish, or against earlier ChessMind
AI configs.

**Working command** (works around the M5 clock-handling gap; see
[Known limitations](#known-limitations)):

```bash
cutechess-cli \
  -engine conf="ChessMind AI" option."Move Time"=200 \
  -engine conf=Stockfish \
  -each tc=300+1 \
  -rounds 2 \
  -pgnout /tmp/match.pgn
```

What each piece does:

- `conf="ChessMind AI"` reuses the engine entry from the same `engines.json`
  the GUI uses, so paths and options stay in one place.
- `option."Move Time"=200` clamps ChessMind AI's per-move think to 200 ms.
  This is the workaround — the engine ignores `wtime`/`btime` so without it
  the engine self-defaults to 1 s/move, and a few moves of accumulated time
  is enough to forfeit the game on the tournament clock.
- `tc=300+1` gives each side 5 minutes + 1 s/move increment. Stockfish
  honors this; ChessMind AI's actual wall time stays well under it thanks to
  `Move Time=200`.
- `-rounds 2` plays 2 games per pairing (one as white, one as black with
  `-repeat`).
- `-pgnout` writes a PGN so you can step through the games in any GUI later.

Useful follow-on flags:

- `-each st=2` — force a fixed `go movetime 2000` per move on *both* engines
  (alternative to `-each tc=…` with the `Move Time` override). Currently does
  not work cleanly for ChessMind AI without a slightly lower Move Time
  override, again due to transmission-margin issues; see limitations.
- `-debug` — print every UCI command sent/received. Goes at the **end** of
  the command line; put it anywhere else and cutechess-cli warns about an
  empty value.
- `-resign movecount=3 score=600` — resign if down 6 pawns for 3 plies in a
  row, speeds up obviously-lost games.

---

## Known limitations

These are M5 → M6 work and you should expect to hit them until then.

| Limitation | Symptom | Workaround |
| --- | --- | --- |
| `wtime` / `btime` ignored | Engine takes its default `Move Time` per move regardless of tournament clock; forfeits a long game on time. | Use generous clocks in the GUI, or set `option."Move Time"=200` in cutechess-cli. |
| No transmission margin on `movetime` | Strict per-move deadlines (`cutechess-cli -each st=N`) can race the clock on the final response. | Use `Move Time` UCI option instead of `st=`; keep at least 100 ms of slack. |

Both are documented in [src/chess_mind_ai/uci.py:23-25](../src/chess_mind_ai/uci.py#L23-L25)
and are scheduled for M6 (fair tournament time management).

---

## Troubleshooting

**"CPU" radio is greyed out in New Game.** Cute Chess doesn't know about any
engines yet. Quit, re-add via Settings → Engines → Add, or hand-edit
`engines.json` (with Cute Chess closed). See section 2.

**Engine starts then immediately disappears.** Run `./uci` directly in a
terminal to see the error. The most common cause on macOS is the
`com.apple.provenance` xattr on `.pth` files breaking the editable install —
the `./uci` script tries to fix this on every launch, but if you ran
`uv sync` after, you may need to re-run `./uci` once to clear the markers.

**LLM scorer fails with "GEMINI_API_KEY is not set".** Cute Chess didn't
inherit the env var. Quit Cute Chess, `export GEMINI_API_KEY=…` in the
terminal, then re-launch `cutechess` from that same shell.

**Engine plays absurdly badly or hangs.** Try the hand-coded scorer first
(empty `Prompt` option) — that isolates whether the issue is the UCI layer
or the LLM/sandbox. If hand-coded play is fine, set `--show-generated-code`
in a terminal-CLI invocation with the same prompt to inspect the LLM output.
