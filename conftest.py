"""Make `src/chess_mind_ai` importable without relying on the editable install.

Background: uv on macOS marks `.pth` files it writes into the venv with both
the UF_HIDDEN filesystem flag and the `com.apple.provenance` extended
attribute. Python 3.13.13+ and 3.14 silently skip `.pth` files marked with
either, so the editable install never lands on sys.path — breaking the
`chess-mind-ai` entry point until the upstream issue is resolved. Worse, uv
re-applies both markers on every `uv run`, so `uv run chess-mind-ai ...`
cannot be fixed by clearing them once.

This conftest avoids the problem for tests by injecting `src/` directly into
sys.path on pytest collection. The CLI entry-point script needs a different
workaround — see `./play` in the repo root, which clears both markers AND
calls `.venv/bin/chess-mind-ai` directly (bypassing `uv run`).
"""
import sys
from pathlib import Path

_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
