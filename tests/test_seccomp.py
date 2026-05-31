"""Tests for the seccomp syscall filter (Linux only).

seccomp is irreversible for a process, so the "filter blocks X" assertions run
in a fresh child interpreter via subprocess. On non-Linux (or where libseccomp
is unavailable) these are skipped — the worker degrades to reduced isolation
there, which `test_worker.py` covers.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from chess_mind_ai.sandbox.seccomp import seccomp_available

pytestmark = pytest.mark.skipif(
    not seccomp_available(),
    reason="seccomp/libseccomp not available on this platform",
)


def _run_child(body: str) -> subprocess.CompletedProcess:
    """Run `body` in a fresh interpreter that can import the package."""
    script = textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ},
    )


def test_seccomp_reports_available_on_this_platform():
    # The module-level skipif already gates this, so reaching here means True.
    assert seccomp_available() is True


def test_filter_blocks_escape_syscalls_but_allows_compute():
    # Import os/socket BEFORE locking down (imports need openat, which the
    # filter denies). Then assert: compute works, socket() and open() are denied.
    proc = _run_child(
        """
        import os, socket, sys
        from chess_mind_ai.sandbox.seccomp import apply_seccomp_filter
        if not apply_seccomp_filter():
            print("NOAPPLY"); sys.exit(11)
        # Pure compute must still work under the filter.
        assert sum(range(1000)) == 499500
        # Opening a network socket must be denied.
        try:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            print("SOCKET_OK"); sys.exit(12)
        except OSError:
            pass
        # Opening a new file must be denied.
        try:
            os.open("/etc/hostname", os.O_RDONLY)
            print("OPEN_OK"); sys.exit(13)
        except OSError:
            pass
        print("PASS"); sys.exit(0)
        """
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "PASS" in proc.stdout


def test_filter_blocks_subprocess_exec():
    # execve must be denied: a generated scorer must not be able to spawn a shell.
    proc = _run_child(
        """
        import subprocess, sys
        from chess_mind_ai.sandbox.seccomp import apply_seccomp_filter
        if not apply_seccomp_filter():
            print("NOAPPLY"); sys.exit(11)
        try:
            subprocess.run(["/bin/true"])
            print("EXEC_OK"); sys.exit(12)
        except OSError:
            print("PASS"); sys.exit(0)
        print("NOEXCEPT"); sys.exit(13)
        """
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "PASS" in proc.stdout
