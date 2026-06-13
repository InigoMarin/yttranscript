"""Tests for yttranscript.web: SSE streaming and _serve_api flow."""

from __future__ import annotations

import http.server
import json
import threading
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from yttranscript import web


class _Harness:
    """Run a TranscriptHandler server in a thread for the duration of a test."""

    def __init__(self):
        self.srv = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), web.TranscriptHandler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()

    def stream(self, path, headers=None):
        """Open a streaming connection and return the full body."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        resp = urllib.request.urlopen(req, timeout=3)
        return resp.read().decode()


@pytest.fixture(autouse=True)
def _fresh_slots():
    original = web._transcription_slots
    web._transcription_slots = threading.BoundedSemaphore(
        web.MAX_CONCURRENT_TRANSCRIPTIONS)
    yield
    web._transcription_slots = original


def _parse_sse_events(body: str) -> list[dict]:
    """Parse SSE body into a list of event dicts."""
    events = []
    for block in body.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            events.append(json.loads(block[len("data: "):]))
    return events


# --- _serve_api: successful flow ------------------------------------------

def test_sse_done_event_on_success():
    """A successful process_video yields log events + a final 'done' event."""
    def fake_process_video(**kwargs):
        cb = kwargs.get("log_callback")
        if cb:
            cb("info", "Downloading...")
            cb("success", "Done!")
        return ("My Video Title", None)

    with patch("yttranscript.web.process_video", side_effect=fake_process_video), \
         patch("yttranscript.web.load_config", return_value={}), \
         patch("yttranscript.web.sanitize_filename", return_value="My_Video_Title"):
        with _Harness() as h:
            body = h.stream(
                "/api?url=https://youtube.com/watch?v=abc&format=txt",
                headers={"Origin": f"http://localhost:{h.port}"})

    events = _parse_sse_events(body)
    types = [e["type"] for e in events]

    assert "info" in types
    assert "success" in types
    assert events[-1]["type"] == "done"
    assert events[-1]["title"] == "My Video Title"
    assert events[-1]["filename"] == "My_Video_Title.txt"


def test_sse_done_event_json_format():
    def fake_pv(**kwargs):
        cb = kwargs.get("log_callback")
        if cb:
            cb("info", "ok")
        return ("T", None)

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            body = h.stream(
                "/api?url=https://youtube.com/watch?v=x&format=json",
                headers={"Origin": f"http://localhost:{h.port}"})

    events = _parse_sse_events(body)
    assert events[-1]["filename"].endswith(".json")


def test_sse_done_event_vtt_format():
    def fake_pv(**kwargs):
        cb = kwargs.get("log_callback")
        if cb:
            cb("info", "ok")
        return ("T", None)

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            body = h.stream(
                "/api?url=https://youtube.com/watch?v=x&format=vtt",
                headers={"Origin": f"http://localhost:{h.port}"})

    events = _parse_sse_events(body)
    assert events[-1]["filename"].endswith(".vtt")


def test_sse_stdout_captured_in_done_event():
    """stdout written during process_video appears in the done event text."""
    import sys as _sys
    from yttranscript.log import ThreadLocalStdout

    original = _sys.stdout
    _sys.stdout = ThreadLocalStdout(original)
    try:
        def fake_pv(**kwargs):
            _sys.stdout.write("Transcript line 1\n")
            _sys.stdout.write("Transcript line 2\n")
            return ("T", None)

        with patch("yttranscript.web.process_video", side_effect=fake_pv), \
             patch("yttranscript.web.load_config", return_value={}):
            with _Harness() as h:
                body = h.stream(
                    "/api?url=https://youtube.com/watch?v=x&format=txt",
                    headers={"Origin": f"http://localhost:{h.port}"})
    finally:
        _sys.stdout = original

    events = _parse_sse_events(body)
    done = events[-1]
    assert "Transcript line 1" in done["text"]
    assert "Transcript line 2" in done["text"]


# --- _serve_api: error handling -------------------------------------------

def test_sse_error_on_transcript_error():
    """When process_video raises TranscriptError, an error event is sent."""
    from yttranscript.util import TranscriptError

    def fake_pv(**kwargs):
        cb = kwargs.get("log_callback")
        if cb:
            cb("error", "Something went wrong")
        raise TranscriptError("Transcription failed")

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            body = h.stream(
                "/api?url=https://youtube.com/watch?v=x",
                headers={"Origin": f"http://localhost:{h.port}"})

    events = _parse_sse_events(body)
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) >= 1
    assert "Transcription failed" in error_events[-1]["message"]
    assert "done" not in [e["type"] for e in events]


def test_sse_uncaught_exception_sends_error():
    """An unexpected exception type sends an error event and closes."""
    def fake_pv(**kwargs):
        raise RuntimeError("Unexpected boom")

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            body = h.stream(
                "/api?url=https://youtube.com/watch?v=x",
                headers={"Origin": f"http://localhost:{h.port}"})

    events = _parse_sse_events(body)
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) >= 1
    assert "done" not in [e["type"] for e in events]


# --- _serve_api: parameter passing ----------------------------------------

def test_api_passes_url_and_lang():
    received = {}

    def fake_pv(**kwargs):
        received.update(kwargs)
        return ("T", None)

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            h.stream(
                "/api?url=https://youtube.com/watch?v=x&lang=es&format=json&timestamps=1",
                headers={"Origin": f"http://localhost:{h.port}"})

    assert received["url"] == "https://youtube.com/watch?v=x"
    assert received["lang"] == "es"
    assert received["fmt"] == "json"
    assert received["timestamps"] is True
    assert received["stdout_mode"] is True


def test_api_passes_summarize_flag():
    received = {}

    def fake_pv(**kwargs):
        received.update(kwargs)
        return ("T", None)

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            h.stream(
                "/api?url=https://youtube.com/watch?v=x&summarize=1",
                headers={"Origin": f"http://localhost:{h.port}"})

    assert received["summarize"] is True


def test_api_passes_config_values():
    received = {}

    def fake_pv(**kwargs):
        received.update(kwargs)
        return ("T", None)

    config = {
        "summarize_cmd": "llama-cli",
        "summarize_prompt": "Resume",
        "summarize_timeout": 120,
        "fallback_lang": "es",
    }
    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value=config):
        with _Harness() as h:
            h.stream(
                "/api?url=https://youtube.com/watch?v=x",
                headers={"Origin": f"http://localhost:{h.port}"})

    assert received["summarize_cmd"] == "llama-cli"
    assert received["summarize_prompt"] == "Resume"
    assert received["summarize_timeout"] == 120
    assert received["fallback_lang"] == "es"


def test_api_passes_summarize_backend_from_query():
    received = {}

    def fake_pv(**kwargs):
        received.update(kwargs)
        return ("T", None)

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}), \
         patch("yttranscript.web.os.environ.get", return_value="envkey"):
        with _Harness() as h:
            h.stream(
                "/api?url=https://youtube.com/watch?v=x&summarize=1&summarize_backend=api",
                headers={"Origin": f"http://localhost:{h.port}"})

    assert received["summarize"] is True
    assert received["summarize_backend"] == "api"
    assert received["summarize_api_key"] == "envkey"


def test_api_summarize_backend_falls_back_to_config():
    received = {}

    def fake_pv(**kwargs):
        received.update(kwargs)
        return ("T", None)

    config = {"summarize_backend": "api"}
    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value=config), \
         patch("yttranscript.web.os.environ.get", return_value=None):
        with _Harness() as h:
            h.stream(
                "/api?url=https://youtube.com/watch?v=x&summarize=1",
                headers={"Origin": f"http://localhost:{h.port}"})

    assert received["summarize_backend"] == "api"
    assert received["summarize_api_key"] is None


# --- title fallback -------------------------------------------------------

def test_title_fallback_to_transcript():
    """When process_video returns None, title defaults to 'transcript'."""
    with patch("yttranscript.web.process_video", return_value=None), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            body = h.stream(
                "/api?url=https://youtube.com/watch?v=x",
                headers={"Origin": f"http://localhost:{h.port}"})

    events = _parse_sse_events(body)
    done = events[-1]
    assert done["type"] == "done"
    assert done["title"] == "transcript"
    assert "transcript.txt" in done["filename"]


# --- binary format (PDF/EPUB/DOCX) via download ---------------------------

def test_binary_format_uses_file_output():
    """Binary formats pass stdout_mode=False and output_dir to process_video."""
    received = {}

    def fake_pv(**kwargs):
        received.update(kwargs)
        out_dir = kwargs.get("output_dir")
        if out_dir:
            from pathlib import Path
            (Path(out_dir) / "video.pdf").write_bytes(b"%PDF-1.4 fake")
        return ("video", None)

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            body = h.stream(
                "/api?url=https://youtube.com/watch?v=x&format=pdf",
                headers={"Origin": f"http://localhost:{h.port}"})

    assert received["stdout_mode"] is False
    assert received["output_dir"] is not None
    assert "yttranscript-downloads" in received["output_dir"]

    events = _parse_sse_events(body)
    done = events[-1]
    assert done["type"] == "done"
    assert "/download/" in done["download"]
    assert done["filename"].endswith(".pdf")


def test_binary_format_serves_actual_file():
    """The download link points to a file with real binary content."""
    def fake_pv(**kwargs):
        out_dir = kwargs.get("output_dir")
        if out_dir:
            from pathlib import Path
            (Path(out_dir) / "video.epub").write_bytes(b"PK\x03\x04 epub content")
        return ("video", None)

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            api_body = h.stream(
                "/api?url=https://youtube.com/watch?v=x&format=epub",
                headers={"Origin": f"http://localhost:{h.port}"})

    events = _parse_sse_events(api_body)
    done = events[-1]
    assert done["type"] == "done"
    download_path = done["download"]

    with _Harness() as h:
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{h.port}{download_path}")
        content = resp.read()

    assert content == b"PK\x03\x04 epub content"


def test_text_format_still_uses_stdout_mode():
    """Text formats continue to use stdout_mode=True (no output_dir)."""
    received = {}

    def fake_pv(**kwargs):
        received.update(kwargs)
        return ("video", None)

    with patch("yttranscript.web.process_video", side_effect=fake_pv), \
         patch("yttranscript.web.load_config", return_value={}):
        with _Harness() as h:
            h.stream(
                "/api?url=https://youtube.com/watch?v=x&format=txt",
                headers={"Origin": f"http://localhost:{h.port}"})

    assert received["stdout_mode"] is True
    assert received.get("output_dir") is None


# --- HTML page serving -----------------------------------------------------

def test_web_html_loaded_from_file():
    assert "<!DOCTYPE html>" in web._WEB_HTML
    assert "yttranscript" in web._WEB_HTML


def test_html_page_served():
    with _Harness() as h:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{h.port}/")
        body = resp.read().decode("utf-8")
        assert "<!DOCTYPE html>" in body
        assert "text/html" in resp.headers["Content-Type"]
