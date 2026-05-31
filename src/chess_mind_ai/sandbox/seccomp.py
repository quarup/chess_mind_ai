"""seccomp-bpf syscall filtering for the scorer worker (Linux only).

This is the syscall-restriction axis of the OS-isolation layer described in
`docs/scorer-sandbox-design.md` §11–12. It composes with — and is orthogonal to
— the `unshare` namespace backend in `worker.py`: `unshare` controls *what the
process can see* (no network, isolated mounts), while seccomp controls *which
syscalls it may invoke at all*. Stacked, an escape attempt faces both "there is
no network" and "`socket()` is uncallable".

Implementation note (corrects the pessimistic assumption in the design doc that
seccomp "needs a compiler + network"): we drive the system **libseccomp** via
`ctypes`. That needs **no** Python binding, **no** compiler, and **no** network
— only `libseccomp.so.2`, which ships with the base system. If the library is
absent or the filter cannot be installed, `apply_seccomp_filter` degrades to
"reduced isolation" (logs a warning, returns False) rather than failing — the
worker still runs behind the AST validator + restricted builtins + setrlimit +
(on Linux) the `unshare` namespaces.

Policy: a **default-deny allowlist**. The default action is `ERRNO(EPERM)` (not
`KILL`) so that a benign-but-unlisted syscall degrades to a Python-level error
— which the worker reports cleanly and the parent turns into neutral fallback —
rather than a hard crash that looks like a sandbox bug. Escape-class syscalls
(`socket`, `openat`, `execve`, `clone`, `ptrace`, …) are simply not on the
allowlist, so they receive EPERM. The allowlist covers what a CPython process
running a pure, already-loaded compute function needs to finish and write its
result over the stdout pipe.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import sys

logger = logging.getLogger(__name__)

# libseccomp action constants (from <seccomp.h>).
_SCMP_ACT_ALLOW = 0x7FFF0000


def _scmp_act_errno(errno: int) -> int:
    # SCMP_ACT_ERRNO(x) == 0x00050000 | (x & 0x0000ffff)
    return 0x00050000 | (errno & 0x0000FFFF)


_EPERM = 1
_DEFAULT_ACTION = _scmp_act_errno(_EPERM)

# Syscalls a pure, already-loaded compute function needs to run and to emit its
# result over the stdout pipe (plus what CPython touches at runtime/shutdown).
# Anything not here gets EPERM. Resolved by name per-arch via libseccomp, so
# names that don't exist on this kernel/arch are simply skipped.
_ALLOWED_SYSCALLS: tuple[str, ...] = (
    # I/O on already-open fds (stdin already read; stdout pipe for the result).
    "read", "readv", "write", "writev", "close", "lseek", "fcntl", "ioctl",
    "dup", "dup2", "dup3",
    # stat on already-open fds (CPython internals).
    "fstat", "newfstatat", "stat", "lstat", "statx",
    # Memory management (malloc/GC/interpreter).
    "mmap", "munmap", "mremap", "mprotect", "brk", "madvise",
    # Signals (CPython installs handlers; clean teardown).
    "rt_sigaction", "rt_sigprocmask", "rt_sigreturn", "sigaltstack",
    # Threading primitive / GIL. Blocking these would risk a deadlock rather
    # than a clean error, so they are always allowed.
    "futex", "futex_waitv", "set_robust_list", "get_robust_list",
    # Misc runtime bookkeeping.
    "getpid", "gettid", "getrandom", "arch_prctl", "set_tid_address", "rseq",
    "sched_yield", "sched_getaffinity", "getrlimit", "prlimit64",
    # Clocks (some code paths read time; harmless).
    "clock_gettime", "clock_gettime64", "clock_getres", "gettimeofday",
    "nanosleep", "clock_nanosleep",
    # Event loops / poll that buffered IO may touch.
    "poll", "ppoll", "select", "pselect6", "epoll_wait", "epoll_pwait",
    # Process exit.
    "exit", "exit_group", "restart_syscall",
)


def seccomp_available() -> bool:
    """True if we are on Linux and libseccomp can be loaded via ctypes."""
    if sys.platform != "linux":
        return False
    return _load_libseccomp() is not None


def _load_libseccomp() -> ctypes.CDLL | None:
    for name in (ctypes.util.find_library("seccomp"), "libseccomp.so.2", "libseccomp.so"):
        if not name:
            continue
        try:
            return ctypes.CDLL(name, use_errno=True)
        except OSError:
            continue
    return None


def apply_seccomp_filter() -> bool:
    """Install the seccomp allowlist on the *current* process. Never raises.

    Returns True if the filter was loaded, False if seccomp is unavailable or
    installation failed (caller should treat False as "reduced isolation").
    Must be called *after* all imports/file IO the process still needs, because
    once loaded the filter is irreversible and `openat` is denied.
    """
    if sys.platform != "linux":
        return False

    lib = _load_libseccomp()
    if lib is None:
        logger.warning(
            "scorer sandbox: libseccomp not loadable; running with reduced "
            "isolation (no seccomp syscall filter)"
        )
        return False

    try:
        return _build_and_load(lib)
    except Exception as e:  # noqa: BLE001 — degrade, never crash the worker
        logger.warning("scorer sandbox: seccomp filter not installed (%s); "
                       "reduced isolation", e)
        return False


def _build_and_load(lib: ctypes.CDLL) -> bool:
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                     ctypes.c_uint]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.restype = None
    lib.seccomp_release.argtypes = [ctypes.c_void_p]

    ctx = lib.seccomp_init(_DEFAULT_ACTION)
    if not ctx:
        logger.warning("scorer sandbox: seccomp_init failed; reduced isolation")
        return False

    try:
        for name in _ALLOWED_SYSCALLS:
            nr = lib.seccomp_syscall_resolve_name(name.encode("ascii"))
            if nr < 0:  # __NR_SCMP_ERROR: not present on this arch/kernel.
                continue
            # rc<0 here just means this one rule didn't add; keep going so a
            # single odd syscall name can't disable the whole filter.
            lib.seccomp_rule_add(ctx, _SCMP_ACT_ALLOW, nr, 0)

        rc = lib.seccomp_load(ctx)  # also sets NO_NEW_PRIVS (libseccomp default)
        if rc != 0:
            logger.warning("scorer sandbox: seccomp_load failed (rc=%d); "
                           "reduced isolation", rc)
            return False
        return True
    finally:
        lib.seccomp_release(ctx)
