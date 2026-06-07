"""Tests for yttranscript.summarize: command piping and output parsing."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from yttranscript.summarize import summarize_text


def _cp(returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr="")


def _fake_script_writer(response_text: str):
    """Return a side_effect that writes fake `script` output to the capture file.

    `script -qec <cmd> <outfile>` writes terminal output to <outfile>. We mock
    subprocess.run so that it writes our fake output to args[3] (the outfile).
    """
    def side_effect(args, **kwargs):
        outfile = args[3]  # ['script', '-qec', cmd, outfile]
        with open(outfile, "w") as f:
            f.write("llama-cli banner\n")
            f.write("> Summarize this\n")
            f.write(response_text + "\n")
            f.write("[ Prompt: 100 tokens ]\n")
            f.write("Exiting...\n")
        return _cp(0)
    return side_effect


# --- success cases --------------------------------------------------------

def test_summarize_success_returns_response():
    fake = _fake_script_writer("This is the summary.")
    with patch("yttranscript.summarize.subprocess.run", side_effect=fake):
        result = summarize_text("body text", "llama-cli -m x", "Summarize this")
    assert result is not None
    assert "This is the summary." in result


def test_summarize_multiline_response():
    response = "Line one\nLine two\nLine three"
    fake = _fake_script_writer(response)
    with patch("yttranscript.summarize.subprocess.run", side_effect=fake):
        result = summarize_text("body", "cmd", "prompt")
    assert result is not None
    for line in ("Line one", "Line two", "Line three"):
        assert line in result


def test_summarize_strips_thinking_blocks():
    response = "[Start thinking]\ninternal reasoning\n[End thinking]\nVisible answer"
    fake = _fake_script_writer(response)
    with patch("yttranscript.summarize.subprocess.run", side_effect=fake):
        result = summarize_text("body", "cmd", "prompt")
    assert result is not None
    assert "Visible answer" in result
    assert "internal reasoning" not in result


def test_summarize_strips_unclosed_thinking():
    response = "[Start thinking]\ntruncated thinking\n"
    fake = _fake_script_writer(response)
    with patch("yttranscript.summarize.subprocess.run", side_effect=fake):
        result = summarize_text("body", "cmd", "prompt")
    # Falls back to raw output when clean is empty
    assert result is not None
    assert len(result) > 0


def test_summarize_strips_ansi_escape_codes():
    response = "\033[32mGreen text\033[0m here"
    fake = _fake_script_writer(response)
    with patch("yttranscript.summarize.subprocess.run", side_effect=fake):
        result = summarize_text("body", "cmd", "prompt")
    assert result is not None
    assert "\033[32m" not in result
    assert "Green text" in result


def test_summarize_strips_spinner_residue():
    response = "| / - \\ Processing done"
    fake = _fake_script_writer(response)
    with patch("yttranscript.summarize.subprocess.run", side_effect=fake):
        result = summarize_text("body", "cmd", "prompt")
    assert result is not None
    assert "Processing done" in result


# --- failure cases --------------------------------------------------------

def test_summarize_command_failure_returns_none():
    with patch("yttranscript.summarize.subprocess.run", return_value=_cp(1)):
        result = summarize_text("body", "cmd", "prompt")
    assert result is None


def test_summarize_timeout_returns_none():
    with patch("yttranscript.summarize.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="script", timeout=1)):
        result = summarize_text("body", "cmd", "prompt", timeout=1)
    assert result is None


def test_summarize_command_not_found_returns_none():
    with patch("yttranscript.summarize.subprocess.run",
               side_effect=FileNotFoundError("script not found")):
        result = summarize_text("body", "cmd", "prompt")
    assert result is None


def test_summarize_empty_output_returns_none():
    def write_empty(args, **kwargs):
        outfile = args[3]
        with open(outfile, "w") as f:
            f.write("")  # empty
        return _cp(0)
    with patch("yttranscript.summarize.subprocess.run", side_effect=write_empty):
        result = summarize_text("body", "cmd", "prompt")
    assert result is None


# --- command expansion ----------------------------------------------------

def test_summarize_empty_cmd_returns_none():
    result = summarize_text("body", "", "prompt")
    assert result is None


def test_summarize_whitespace_cmd_returns_none():
    result = summarize_text("body", "   ", "prompt")
    assert result is None


def test_summarize_expands_user_path():
    """~ and $ENV in the command are expanded before execution."""
    captured_cmd = []

    def capture(args, **kwargs):
        captured_cmd.append(args[2])  # shell_cmd string
        outfile = args[3]
        with open(outfile, "w") as f:
            f.write("> p\nOK\n[ Prompt: x ]\nExiting...\n")
        return _cp(0)

    with patch("yttranscript.summarize.subprocess.run", side_effect=capture):
        summarize_text("body", "llama-cli -m ~/models/x.gguf", "prompt")
    # The shell command should contain the expanded path (not ~/)
    shell_cmd = captured_cmd[0]
    assert "~" not in shell_cmd


def test_summarize_prompt_prepended_to_input():
    """The prompt is prepended to the text body in the input file."""
    captured_input = []

    def capture(args, **kwargs):
        outfile = args[3]
        # The input file was already written by summarize_text; find it.
        # It's the second tempfile; we read it from the shell_cmd cat <file>
        shell_cmd = args[2]
        # Extract filename from "cat '<file>' | ..."
        import shlex
        parts = shlex.split(shell_cmd)
        input_file = parts[1]
        captured_input.append(open(input_file).read())
        with open(outfile, "w") as f:
            f.write("> p\nOK\n[ Prompt: x ]\nExiting...\n")
        return _cp(0)

    with patch("yttranscript.summarize.subprocess.run", side_effect=capture):
        summarize_text("BODY", "cmd", "PROMPT")
    assert captured_input[0] == "PROMPT BODY"
