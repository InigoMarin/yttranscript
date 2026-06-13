"""Tests for yttranscript.summarize: command piping and HTTP API backends."""

from __future__ import annotations

import io
import json
import socket
import subprocess
import urllib.error
from unittest.mock import patch

from yttranscript.summarize import (
    derive_models_url,
    list_models,
    summarize,
    summarize_text,
    summarize_text_api,
)


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


# --- API backend ----------------------------------------------------------

class _FakeResp:
    """Fake ``urllib.request.urlopen`` context manager returning canned bytes."""
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _api_json(content: str = "This is the summary.") -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def test_api_summarize_success_returns_content():
    fake = _FakeResp(_api_json("Bullet one\nBullet two"))
    with patch("yttranscript.summarize.urllib.request.urlopen", return_value=fake):
        result = summarize_text_api("body", "https://x/v1/chat/completions", "gpt-x", "key", "Summarize")
    assert result == "Bullet one\nBullet two"


def test_api_summarize_strips_whitespace():
    fake = _FakeResp(_api_json("   trimmed text   "))
    with patch("yttranscript.summarize.urllib.request.urlopen", return_value=fake):
        result = summarize_text_api("body", "https://x", "m", "k", "p")
    assert result == "trimmed text"


def test_api_summarize_prompt_in_payload():
    captured = {}
    fake = _FakeResp(_api_json("ok"))

    def capture(req, **kw):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return fake

    with patch("yttranscript.summarize.urllib.request.urlopen", side_effect=capture):
        summarize_text_api("BODY", "https://x", "m", "k", "PROMPT")
    msg = captured["body"]["messages"][0]["content"]
    assert msg == "PROMPT BODY"
    assert captured["body"]["model"] == "m"
    assert captured["body"]["temperature"] == 0.3


def test_api_summarize_sends_bearer_auth():
    captured = {}
    fake = _FakeResp(_api_json("ok"))

    def capture(req, **kw):
        captured["auth"] = req.get_header("Authorization")
        captured["ctype"] = req.get_header("Content-type")
        return fake

    with patch("yttranscript.summarize.urllib.request.urlopen", side_effect=capture):
        summarize_text_api("b", "https://x", "m", "SECRET", "p")
    assert captured["auth"] == "Bearer SECRET"
    assert captured["ctype"] == "application/json"


# --- API backend: failure cases -------------------------------------------

def test_api_summarize_empty_url_returns_none():
    result = summarize_text_api("body", "", "m", "k", "p")
    assert result is None


def test_api_summarize_whitespace_url_returns_none():
    result = summarize_text_api("body", "   ", "m", "k", "p")
    assert result is None


def test_api_summarize_empty_key_returns_none():
    result = summarize_text_api("body", "https://x", "m", "", "p")
    assert result is None


def test_api_summarize_empty_model_returns_none():
    result = summarize_text_api("body", "https://x", "", "k", "p")
    assert result is None


def test_api_summarize_http_error_returns_none():
    err = urllib.error.HTTPError(
        "https://x", 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad key"}')
    )
    with patch("yttranscript.summarize.urllib.request.urlopen", side_effect=err):
        result = summarize_text_api("body", "https://x", "m", "k", "p")
    assert result is None


def test_api_summarize_http_error_unreadable_body_returns_none():
    """HTTPError whose body cannot be read still yields None (defensive path)."""
    class _Broken:
        def read(self):
            raise RuntimeError("stream gone")
        def close(self):
            pass
    err = urllib.error.HTTPError("https://x", 500, "Server Error", {}, _Broken())
    with patch("yttranscript.summarize.urllib.request.urlopen", side_effect=err):
        result = summarize_text_api("body", "https://x", "m", "k", "p")
    assert result is None


def test_api_summarize_url_error_returns_none():
    with patch("yttranscript.summarize.urllib.request.urlopen",
               side_effect=urllib.error.URLError("connection refused")):
        result = summarize_text_api("body", "https://x", "m", "k", "p")
    assert result is None


def test_api_summarize_timeout_returns_none():
    with patch("yttranscript.summarize.urllib.request.urlopen",
               side_effect=socket.timeout("timed out")):
        result = summarize_text_api("body", "https://x", "m", "k", "p", timeout=1)
    assert result is None


def test_api_summarize_malformed_json_returns_none():
    fake = _FakeResp(b"not json at all")
    with patch("yttranscript.summarize.urllib.request.urlopen", return_value=fake):
        result = summarize_text_api("body", "https://x", "m", "k", "p")
    assert result is None


def test_api_summarize_unexpected_structure_returns_none():
    fake = _FakeResp(b'{"foo": "bar"}')
    with patch("yttranscript.summarize.urllib.request.urlopen", return_value=fake):
        result = summarize_text_api("body", "https://x", "m", "k", "p")
    assert result is None


def test_api_summarize_empty_content_returns_none():
    fake = _FakeResp(_api_json(""))
    with patch("yttranscript.summarize.urllib.request.urlopen", return_value=fake):
        result = summarize_text_api("body", "https://x", "m", "k", "p")
    assert result is None


# --- dispatcher -----------------------------------------------------------

def test_dispatcher_routes_to_api():
    with patch("yttranscript.summarize.summarize_text_api", return_value="API RESULT") as m_api:
        result = summarize(
            "body", backend="api",
            api_url="https://x", api_model="m", api_key="k", prompt="p",
        )
    m_api.assert_called_once()
    assert result == "API RESULT"


def test_dispatcher_routes_to_cmd():
    with patch("yttranscript.summarize.summarize_text", return_value="CMD RESULT") as m_cmd:
        result = summarize("body", backend="cmd", cmd="llama-cli", prompt="p")
    m_cmd.assert_called_once()
    assert result == "CMD RESULT"


def test_dispatcher_unknown_backend_falls_back_to_cmd():
    with patch("yttranscript.summarize.summarize_text", return_value="CMD") as m_cmd:
        result = summarize("body", backend="weird", cmd="c", prompt="p")
    m_cmd.assert_called_once()
    assert result == "CMD"


# --- derive_models_url ----------------------------------------------------

def test_derive_models_url_standard_suffix():
    assert derive_models_url(
        "https://api.openai.com/v1/chat/completions"
    ) == "https://api.openai.com/v1/models"


def test_derive_models_url_without_suffix_appends():
    # base URL without /chat/completions → append /models
    assert derive_models_url("https://api.openai.com/v1") == "https://api.openai.com/v1/models"
    assert derive_models_url("https://api.openai.com/v1/") == "https://api.openai.com/v1/models"


def test_derive_models_url_custom_port():
    assert derive_models_url(
        "http://localhost:1234/v1/chat/completions"
    ) == "http://localhost:1234/v1/models"


# --- list_models ----------------------------------------------------------

def _models_json() -> bytes:
    return json.dumps({
        "object": "list",
        "data": [
            {"id": "gpt-4o", "object": "model", "created": 1715367600, "owned_by": "openai"},
            {"id": "gpt-4o-mini", "object": "model", "created": 1721260800, "owned_by": "openai"},
            {"id": "o1-preview", "object": "model", "created": 1726099200, "owned_by": "system"},
        ],
    }).encode("utf-8")


def test_list_models_success_returns_sorted_entries():
    fake = _FakeResp(_models_json())
    with patch("yttranscript.summarize.urllib.request.urlopen", return_value=fake):
        result = list_models(
            "https://api.openai.com/v1/chat/completions", "key"
        )
    assert result is not None
    ids = [m["id"] for m in result]
    assert ids == sorted(ids)  # sorted by id
    assert "gpt-4o-mini" in ids
    assert result[0]["owned_by"] in ("openai", "system")
    assert isinstance(result[0]["created"], int)


def test_list_models_uses_derived_url_and_bearer():
    captured = {}
    fake = _FakeResp(_models_json())

    def capture(req, **kw):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        return fake

    with patch("yttranscript.summarize.urllib.request.urlopen", side_effect=capture):
        list_models("https://x/v1/chat/completions", "SECRET")
    assert captured["url"] == "https://x/v1/models"
    assert captured["auth"] == "Bearer SECRET"


def test_list_models_empty_url_returns_none():
    result = list_models("", "key")
    assert result is None


def test_list_models_empty_key_returns_none():
    result = list_models("https://x/v1/chat/completions", "")
    assert result is None


def test_list_models_http_error_returns_none():
    err = urllib.error.HTTPError(
        "https://x", 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad key"}')
    )
    with patch("yttranscript.summarize.urllib.request.urlopen", side_effect=err):
        result = list_models("https://x/v1/chat/completions", "k")
    assert result is None


def test_list_models_http_error_unreadable_body_returns_none():
    """HTTPError whose body cannot be read still yields None (defensive path)."""
    class _Broken:
        def read(self):
            raise RuntimeError("stream gone")
        def close(self):
            pass
    err = urllib.error.HTTPError("https://x", 500, "Server Error", {}, _Broken())
    with patch("yttranscript.summarize.urllib.request.urlopen", side_effect=err):
        result = list_models("https://x/v1/chat/completions", "k")
    assert result is None


def test_list_models_url_error_returns_none():
    with patch("yttranscript.summarize.urllib.request.urlopen",
               side_effect=urllib.error.URLError("connection refused")):
        result = list_models("https://x/v1/chat/completions", "k")
    assert result is None


def test_list_models_timeout_returns_none():
    with patch("yttranscript.summarize.urllib.request.urlopen",
               side_effect=socket.timeout("timed out")):
        result = list_models("https://x/v1/chat/completions", "k", timeout=1)
    assert result is None


def test_list_models_malformed_json_returns_none():
    fake = _FakeResp(b"not json")
    with patch("yttranscript.summarize.urllib.request.urlopen", return_value=fake):
        result = list_models("https://x/v1/chat/completions", "k")
    assert result is None


def test_list_models_empty_data_returns_empty_list():
    fake = _FakeResp(b'{"object": "list", "data": []}')
    with patch("yttranscript.summarize.urllib.request.urlopen", return_value=fake):
        result = list_models("https://x/v1/chat/completions", "k")
    assert result == []


def test_list_models_missing_fields_defaulted():
    fake = _FakeResp(b'{"data": [{"id": "weird"}]}')
    with patch("yttranscript.summarize.urllib.request.urlopen", return_value=fake):
        result = list_models("https://x/v1/chat/completions", "k")
    assert result == [{"id": "weird", "owned_by": "?", "created": None}]
