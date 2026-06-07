"""Logging utilities with thread-local routing for concurrent web requests.

The log functions (info/success/warn/error/debug) consult a per-thread context
that can be set up via the `log_context` and `stdout_capture` context managers.
This lets the web server (ThreadingHTTPServer) run multiple `process_video`
calls in parallel without their log output or stdout writes clobbering each
other, while CLI usage continues to print normally.
"""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from typing import Optional, Callable

VERBOSITY: int = 1  # 0=quiet, 1=normal, 2=verbose


def _supports_color() -> bool:
    """Return True if ANSI color codes should be emitted.

    Honors the NO_COLOR convention (https://no-color.org/), CLICOLOR=0,
    and redirects (non-TTY). Colors are forced on when CLICOLOR_FORCE=1.
    """
    if os.environ.get("CLICOLOR_FORCE"):
        return True
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("CLICOLOR") == "0":
        return False
    return sys.stderr.isatty() or sys.stdout.isatty()


class _ColorsMeta(type):
    """Metaclass that makes color attributes resolve to '' when colors are off."""
    _values = {
        "RED": "\033[91m",
        "GREEN": "\033[92m",
        "YELLOW": "\033[93m",
        "BLUE": "\033[94m",
        "BOLD": "\033[1m",
        "RESET": "\033[0m",
    }

    def __getattr__(cls, name):
        if name in cls._values:
            return cls._values[name] if _supports_color() else ""
        raise AttributeError(name)


class Colors(metaclass=_ColorsMeta):
    """ANSI color constants that auto-disable when stdout/stderr isn't a TTY."""

# Per-thread context for log routing and stdout redirection.
# - log_callback: when set, info/success/warn/error/debug dispatch to it.
# - stderr_logs: when True, info/success/warn are rerouted to stderr (CLI pipe).
# - stdout_buf: when set, the ThreadLocalStdout proxy captures writes into it.
_thread_local = threading.local()


def _emit(level: str, color: str, symbol: str, msg: str, *, stderr_only: bool = False) -> None:
    """Dispatch a log message, honoring thread-local overrides."""
    cb: Optional[Callable[[str, str], None]] = getattr(_thread_local, "log_callback", None)
    if cb is not None:
        cb(level, msg)
        return
    if stderr_only:
        print(f"{color}{symbol}{Colors.RESET} {msg}", file=sys.stderr)
        return
    target = sys.stderr if getattr(_thread_local, "stderr_logs", False) else sys.stdout
    print(f"{color}{symbol}{Colors.RESET} {msg}", file=target)


def info(msg: str) -> None:
    if VERBOSITY >= 1:
        _emit("info", Colors.BLUE, "›", msg)


def success(msg: str) -> None:
    if VERBOSITY >= 1:
        _emit("success", Colors.GREEN, "✓", msg)


def warn(msg: str) -> None:
    if VERBOSITY >= 1:
        _emit("warn", Colors.YELLOW, "⚠", msg)


def error(msg: str) -> None:
    _emit("error", Colors.RED, "✗", msg, stderr_only=True)


def debug(msg: str) -> None:
    if VERBOSITY >= 2:
        _emit("debug", Colors.BLUE, "𝒹", msg, stderr_only=True)


def set_verbosity(level: int) -> None:
    """Set the global verbosity (0=quiet, 1=normal, 2=verbose)."""
    global VERBOSITY
    VERBOSITY = level


@contextmanager
def log_context(log_callback: Optional[Callable[[str, str], None]] = None, *, stdout_mode: bool = False):
    """Set up per-thread log routing for the duration of the block.

    - log_callback: if given (web server mode), log functions dispatch to it.
    - stdout_mode: if True without a callback (CLI piping), reroute info/success/
      warn to stderr so the transcript on stdout stays clean.

    Restores the previous context on exit (nested-call safe).
    """
    prev_cb = getattr(_thread_local, "log_callback", None)
    prev_stderr_logs = getattr(_thread_local, "stderr_logs", False)
    _thread_local.log_callback = log_callback
    _thread_local.stderr_logs = stdout_mode and log_callback is None
    try:
        yield
    finally:
        _thread_local.log_callback = prev_cb
        _thread_local.stderr_logs = prev_stderr_logs


@contextmanager
def stdout_capture(buf):
    """Capture this thread's stdout into `buf` via the ThreadLocalStdout proxy.

    Requires the proxy to be installed (see web.run_server). No-op capture
    happens per-thread: other threads keep writing to their own buf/original.
    """
    prev = getattr(_thread_local, "stdout_buf", None)
    _thread_local.stdout_buf = buf
    try:
        yield
    finally:
        _thread_local.stdout_buf = prev


class ThreadLocalStdout:
    """sys.stdout proxy that dispatches writes to a per-thread buffer when set.

    Replaces the previous `sys.stdout = buf` (process-global, racy under
    ThreadingHTTPServer). When no buffer is set on the current thread, writes
    fall through to the original stdout transparently.
    """

    def __init__(self, original):
        self._original = original

    def _target(self):
        buf = getattr(_thread_local, "stdout_buf", None)
        return buf if buf is not None else self._original

    def write(self, s):
        return self._target().write(s)

    def flush(self):
        return self._target().flush()

    def fileno(self):
        return self._target().fileno()

    def isatty(self):
        return self._target().isatty()

    def writable(self):
        return self._target().writable()

    def readable(self):
        return self._target().readable()

    def seekable(self):
        return self._target().seekable()

    def __getattr__(self, name):
        # Fallback for any other attribute access (encoding, newlines, ...).
        return getattr(self._target(), name)
