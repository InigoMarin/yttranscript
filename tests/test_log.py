"""Tests for yttranscript.log: thread-local routing, context managers."""

from __future__ import annotations

import io
import sys
import threading

import pytest

from yttranscript import log
from yttranscript.log import (
    Colors,
    ThreadLocalStdout,
    log_context,
    stdout_capture,
    set_verbosity,
)


@pytest.fixture(autouse=True)
def _reset_thread_local():
    """Clear thread-local state before and after each test."""
    log._thread_local.__dict__.clear()
    yield
    log._thread_local.__dict__.clear()


# --- set_verbosity --------------------------------------------------------

def test_set_verbosity_changes_threshold():
    old = log.VERBOSITY
    try:
        set_verbosity(0)
        assert log.VERBOSITY == 0
        set_verbosity(2)
        assert log.VERBOSITY == 2
    finally:
        log.VERBOSITY = old


def test_verbosity_zero_suppresses_info(capsys):
    old = log.VERBOSITY
    log.VERBOSITY = 0
    try:
        log.info("hidden")
        log.success("hidden")
        log.warn("hidden")
        captured = capsys.readouterr()
        assert "hidden" not in captured.out
        assert "hidden" not in captured.err
    finally:
        log.VERBOSITY = old


def test_verbosity_zero_still_shows_error(capsys):
    old = log.VERBOSITY
    log.VERBOSITY = 0
    try:
        log.error("visible")
        captured = capsys.readouterr()
        assert "visible" in captured.err
    finally:
        log.VERBOSITY = old


def test_verbosity_two_enables_debug(capsys):
    old = log.VERBOSITY
    log.VERBOSITY = 2
    try:
        log.debug("dbg-msg")
        captured = capsys.readouterr()
        assert "dbg-msg" in captured.err
    finally:
        log.VERBOSITY = old


# --- log_context callback routing -----------------------------------------

def test_log_context_dispatches_to_callback():
    captured = []
    old = log.VERBOSITY
    log.VERBOSITY = 2
    try:
        with log_context(lambda lvl, msg: captured.append((lvl, msg))):
            log.info("i")
            log.success("s")
            log.warn("w")
            log.error("e")
            log.debug("d")
    finally:
        log.VERBOSITY = old

    levels = [lvl for lvl, _ in captured]
    assert levels == ["info", "success", "warn", "error", "debug"]
    assert [msg for _, msg in captured] == ["i", "s", "w", "e", "d"]


def test_log_context_restores_on_exit():
    assert log._thread_local.__dict__.get("log_callback") is None
    with log_context(lambda *a: None):
        assert log._thread_local.log_callback is not None
    assert log._thread_local.__dict__.get("log_callback") is None


def test_log_context_nested_restore():
    outer = lambda *a: None  # noqa: E731
    inner = lambda *a: None  # noqa: E731
    with log_context(outer):
        assert log._thread_local.log_callback is outer
        with log_context(inner):
            assert log._thread_local.log_callback is inner
        assert log._thread_local.log_callback is outer
    assert log._thread_local.__dict__.get("log_callback") is None


def test_log_context_callback_skips_terminal_print(capsys):
    """When a callback is set, nothing is printed to stdout/stderr."""
    with log_context(lambda lvl, msg: None):
        log.info("no-print")
        log.error("no-print-err")
    captured = capsys.readouterr()
    assert "no-print" not in captured.out
    assert "no-print-err" not in captured.err


# --- log_context stdout_mode (CLI piping) ---------------------------------

def test_log_context_stdout_mode_reroutes_to_stderr(capsys):
    with log_context(None, stdout_mode=True):
        log.info("to-stderr")
        log.success("to-stderr")
        log.warn("to-stderr")
    captured = capsys.readouterr()
    assert "to-stderr" in captured.err
    assert "to-stderr" not in captured.out


def test_log_context_stdout_mode_only_without_callback():
    """stdout_mode=True + callback → callback wins, stderr_logs stays False."""
    with log_context(lambda *a: None, stdout_mode=True):
        assert log._thread_local.log_callback is not None
        assert log._thread_local.stderr_logs is False


def test_log_context_normal_mode_prints_to_stdout(capsys):
    with log_context(None, stdout_mode=False):
        log.info("normal")
    captured = capsys.readouterr()
    assert "normal" in captured.out


# --- stdout_capture + ThreadLocalStdout -----------------------------------

def test_stdout_capture_captures_writes():
    original = sys.stdout
    sys.stdout = ThreadLocalStdout(original)
    try:
        buf = io.StringIO()
        with stdout_capture(buf):
            print("captured")
        assert "captured" in buf.getvalue()
    finally:
        sys.stdout = original


def test_stdout_capture_restores_on_exit():
    original = sys.stdout
    sys.stdout = ThreadLocalStdout(original)
    try:
        buf = io.StringIO()
        with stdout_capture(buf):
            print("alpha-msg")
        # After exit, writes go back to original stdout
        buf2 = io.StringIO()
        with stdout_capture(buf2):
            print("beta-msg")
        assert "alpha-msg" in buf.getvalue()
        assert "beta-msg" in buf2.getvalue()
        assert "alpha-msg" not in buf2.getvalue()
    finally:
        sys.stdout = original


def test_thread_local_stdout_isolation():
    """Two threads capturing stdout simultaneously don't pollute each other."""
    original = sys.stdout
    sys.stdout = ThreadLocalStdout(original)
    results = {}
    try:
        def worker(name):
            buf = io.StringIO()
            with stdout_capture(buf):
                for i in range(30):
                    print(f"{name}-{i}")
            results[name] = buf.getvalue()

        t1 = threading.Thread(target=worker, args=("A",))
        t2 = threading.Thread(target=worker, args=("B",))
        t1.start(); t2.start(); t1.join(); t2.join()

        assert results["A"].count("A-") == 30
        assert results["B"].count("B-") == 30
        assert "B-" not in results["A"]
        assert "A-" not in results["B"]
    finally:
        sys.stdout = original


def test_thread_local_stdout_passthrough_without_capture():
    """Without stdout_capture, ThreadLocalStdout writes to the original."""
    original = sys.stdout
    fake = io.StringIO()
    sys.stdout = ThreadLocalStdout(fake)
    try:
        print("passthrough")
        assert "passthrough" in fake.getvalue()
    finally:
        sys.stdout = original


# --- Colors ---------------------------------------------------------------

def test_colors_have_escape_codes(monkeypatch):
    """When colors are enabled, the constants contain ANSI escape sequences."""
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    assert Colors.RED.startswith("\033[")
    assert Colors.RESET == "\033[0m"


def test_colors_disabled_with_no_color(monkeypatch):
    """NO_COLOR env var disables all colors."""
    monkeypatch.setenv("NO_COLOR", "1")
    assert Colors.RED == ""
    assert Colors.GREEN == ""
    assert Colors.YELLOW == ""
    assert Colors.BLUE == ""
    assert Colors.BOLD == ""
    assert Colors.RESET == ""


def test_colors_disabled_with_clicolor_0(monkeypatch):
    """CLICOLOR=0 disables colors."""
    monkeypatch.setenv("CLICOLOR", "0")
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert Colors.RED == ""
