"""Run a generated style scorer in an isolated worker subprocess (M4).

This is the "real boundary" layer described in `docs/scorer-sandbox-design.md`
§11. The generated scorer is loaded and executed in a *separate Python process*
so that, on top of the AST allowlist + restricted builtins, we get:

- **resource limits** (`setrlimit`: address space, CPU seconds, no file writes)
  applied inside the worker before any untrusted code runs;
- a **wall-clock timeout** enforced by the parent (kills the whole process
  group — `RLIMIT_CPU` alone does not fire on a blocking/sleeping loop);
- a **scrubbed environment** (no API keys/secrets) and a temp working dir;
- an optional **OS-isolation backend** selected at runtime: on Linux we wrap the
  worker in unprivileged `unshare` namespaces to drop network and isolate the
  mount/user view. If no backend is available we degrade to "reduced isolation"
  (resource limits + AST layer only) rather than failing.

The portable core (process + setrlimit + wall-clock timeout) runs identically on
macOS and Linux. The macOS Seatbelt backend is a planned follow-up.

Wire protocol: the parent sends a JSON request on stdin and reads a JSON
response on stdout. Everything crossing the boundary is plain data — the board
is sent as a root FEN + UCI move history and rebuilt worker-side.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import chess

logger = logging.getLogger(__name__)

# Defaults. The wall-clock timeout is the primary limit; RLIMIT_CPU is a
# backstop. RLIMIT_AS bounds *virtual* address space, which for CPython sits
# well above resident usage, so the default is generous to avoid killing
# legitimate scorers while still stopping multi-hundred-MB bombs.
DEFAULT_TIMEOUT_S = 2.0
DEFAULT_MEM_MB = 1024
DEFAULT_CPU_S = 10

ScoreTriple = tuple[float, float, float]

# Cached isolation prefix probe result (None = not yet computed).
_ISOLATION_PREFIX: list[str] | None = None


# --------------------------------------------------------------------------- #
# Worker side (runs in the child process)
# --------------------------------------------------------------------------- #

def _apply_resource_limits(mem_mb: int, cpu_s: int) -> None:
    """Best-effort resource caps. Imported lazily — Windows has no `resource`."""
    try:
        import resource
    except ImportError:
        return

    def _set(which: int, soft: int, hard: int) -> None:
        try:
            resource.setrlimit(which, (soft, hard))
        except (ValueError, OSError):
            pass

    if mem_mb:
        nbytes = mem_mb * 1024 * 1024
        _set(resource.RLIMIT_AS, nbytes, nbytes)
    if cpu_s:
        _set(resource.RLIMIT_CPU, cpu_s, cpu_s)
    # No file writes (results return over the stdout pipe, which is unaffected).
    _set(resource.RLIMIT_FSIZE, 0, 0)


def _score_request(req: dict) -> dict:
    # Imported here so an import failure is reported as a worker error, not a
    # crash before we can respond.
    from chess_mind_ai.readonly_board import ReadOnlyBoard
    from chess_mind_ai.sandbox.loader import load_scorer

    scorer = load_scorer(req["source"])

    board = chess.Board(req["root_fen"])
    for uci in req["history"]:
        board.push(chess.Move.from_uci(uci))

    own_color = bool(req["own_color"])
    triples: list[list[float]] = []
    for uci in req["candidates"]:
        move = chess.Move.from_uci(uci)
        # action_score sees the position BEFORE the move; state/trajectory see
        # the position AFTER it (peek applies the move to a read-only copy).
        ctx_before = ReadOnlyBoard(board, own_color)
        ctx_after = ctx_before.peek(move)
        action = scorer.action_score(ctx_before, move)
        state = scorer.state_score(ctx_after)
        trajectory = scorer.trajectory_score(ctx_after)
        triples.append([action, state, trajectory])

    return {"ok": True, "triples": triples}


def _worker_main() -> int:
    try:
        req = json.loads(sys.stdin.read())
        _apply_resource_limits(
            int(req.get("mem_mb", DEFAULT_MEM_MB)),
            int(req.get("cpu_s", DEFAULT_CPU_S)),
        )
        result = _score_request(req)
    except MemoryError:
        result = {"ok": False, "error": "memory limit exceeded"}
    except BaseException as e:  # noqa: BLE001 — report everything as a clean error
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


# --------------------------------------------------------------------------- #
# Parent side (spawns and supervises the worker)
# --------------------------------------------------------------------------- #

def _unshare_probe() -> bool:
    try:
        proc = subprocess.run(
            ["unshare", "--user", "--map-root-user", "--net", "--mount", "true"],
            capture_output=True,
            timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _isolation_prefix(mode: str = "auto") -> list[str]:
    """Command prefix that wraps the worker in an OS-isolation backend.

    Returns the `unshare` namespace wrapper on Linux when unprivileged user
    namespaces are available, else an empty prefix (reduced isolation). Probed
    once and cached.
    """
    if mode == "none":
        return []

    global _ISOLATION_PREFIX
    if _ISOLATION_PREFIX is not None:
        return list(_ISOLATION_PREFIX)

    prefix: list[str] = []
    if sys.platform == "linux" and shutil.which("unshare") and _unshare_probe():
        # No --pid/--fork: unshare execs the interpreter directly (same PID),
        # so the parent's wall-clock kill targets it reliably. --net drops
        # network; --user/--map-root-user enable the unprivileged namespaces.
        prefix = ["unshare", "--user", "--map-root-user", "--net", "--mount"]
    else:
        logger.warning(
            "scorer sandbox: no OS isolation backend available on %s; running "
            "with reduced isolation (resource limits + AST validator only)",
            sys.platform,
        )
    _ISOLATION_PREFIX = prefix
    return list(prefix)


def _scrubbed_env() -> dict[str, str]:
    src_dir = str(Path(__file__).resolve().parents[2])  # .../src
    return {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": src_dir,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def score_candidates_sandboxed(
    source: str,
    board: chess.Board,
    own_color: chess.Color,
    candidate_moves: list[chess.Move],
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    mem_mb: int = DEFAULT_MEM_MB,
    cpu_s: int = DEFAULT_CPU_S,
    isolation: str = "auto",
) -> list[ScoreTriple] | None:
    """Score `candidate_moves` with the generated `source` in an isolated worker.

    Returns one (action, state, trajectory) triple per candidate, or **None** on
    any failure (validation, timeout, resource limit, crash, malformed output).
    Callers should treat None as "fall back to neutral / pure-engine play".
    """
    from chess_mind_ai.sandbox.validator import (
        ScorerValidationError,
        validate_generated_code,
    )

    # Fail fast (and avoid spawning) on statically-invalid code. The worker
    # re-validates via load_scorer as defense-in-depth.
    try:
        validate_generated_code(source)
    except ScorerValidationError:
        return None

    request = json.dumps({
        "source": source,
        "root_fen": board.root().fen(),
        "history": [m.uci() for m in board.move_stack],
        "own_color": bool(own_color),
        "candidates": [m.uci() for m in candidate_moves],
        "mem_mb": mem_mb,
        "cpu_s": cpu_s,
    })

    cmd = _isolation_prefix(isolation) + [sys.executable, "-m", __name__]

    try:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=tmp,
                env=_scrubbed_env(),
                start_new_session=True,
            )
            try:
                out, _err = proc.communicate(request, timeout=timeout_s)
            except subprocess.TimeoutExpired:
                _kill_process_group(proc)
                proc.communicate()
                return None
    except (OSError, ValueError):
        return None

    if proc.returncode != 0:
        return None
    return _parse_response(out, len(candidate_moves))


def _parse_response(out: str, n_expected: int) -> list[ScoreTriple] | None:
    try:
        resp = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(resp, dict) or not resp.get("ok"):
        return None
    triples = resp.get("triples")
    if not isinstance(triples, list) or len(triples) != n_expected:
        return None
    result: list[ScoreTriple] = []
    for tr in triples:
        if not (isinstance(tr, list) and len(tr) == 3):
            return None
        try:
            result.append((float(tr[0]), float(tr[1]), float(tr[2])))
        except (TypeError, ValueError):
            return None
    return result


if __name__ == "__main__":
    sys.exit(_worker_main())
