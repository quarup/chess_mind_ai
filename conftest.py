"""Make `src/chess_mind_ai` importable without relying on the editable install.

Background: uv on macOS sets the UF_HIDDEN filesystem flag on files it writes
into the venv (including `.pth` files in site-packages). Python 3.13.13+ and
3.14 silently skip `.pth` files with that flag set — which breaks editable
installs entirely on macOS until the upstream issue is resolved.

This conftest avoids the problem for tests by injecting `src/` directly into
sys.path on pytest collection. The CLI entry-point script still depends on the
editable install working; running `chflags nohidden .venv/lib/.../*.pth` after
`uv sync` is the current workaround for that path.
"""
import sys
from pathlib import Path

_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
