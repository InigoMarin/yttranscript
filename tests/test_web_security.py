"""Tests for yttranscript.web: CSRF, DNS rebinding, rate limiting."""

from __future__ import annotations

import http.server
import json
import threading
import urllib.error
import urllib.request

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

    def get(self, path, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            return urllib.request.urlopen(req, timeout=2)
        except urllib.error.HTTPError as e:
            return e


@pytest.fixture(autouse=True)
def _fresh_slots():
    """Give each test a fresh semaphore so leftover acquisitions don't leak."""
    original = web._transcription_slots
    web._transcription_slots = threading.BoundedSemaphore(
        web.MAX_CONCURRENT_TRANSCRIPTIONS)
    yield
    web._transcription_slots = original


# --- Home page (public) ---------------------------------------------------

def test_home_page_served():
    with _Harness() as h:
        r = h.get("/")
        assert r.status == 200
        assert "<title>yttranscript</title>" in r.read().decode()


def test_home_page_no_origin_check():
    """Home page is served regardless of Origin header."""
    with _Harness() as h:
        r = h.get("/", {"Origin": "https://evil.com"})
        assert r.status == 200


def test_index_html_alias():
    with _Harness() as h:
        r = h.get("/index.html")
        assert r.status == 200


# --- CSRF: Origin check ---------------------------------------------------

def test_api_rejects_cross_origin():
    with _Harness() as h:
        r = h.get("/api?url=https://youtube.com/watch?v=x",
                  {"Origin": "https://evil.com"})
        assert r.status == 403


def test_api_allows_localhost_origin():
    with _Harness() as h:
        r = h.get("/api", {"Origin": f"http://localhost:{h.port}"})
        assert r.status == 200


def test_api_allows_127_origin():
    with _Harness() as h:
        r = h.get("/api", {"Origin": f"http://127.0.0.1:{h.port}"})
        assert r.status == 200


def test_api_allows_missing_origin():
    """curl / direct nav sends no Origin header."""
    with _Harness() as h:
        r = h.get("/api")
        assert r.status == 200


def test_missing_url_returns_json_error():
    with _Harness() as h:
        r = h.get("/api", {"Origin": f"http://localhost:{h.port}"})
        data = json.loads(r.read().decode())
        assert data == {"error": "Missing url parameter"}


# --- DNS rebinding: Host check --------------------------------------------

def test_api_rejects_bad_host():
    with _Harness() as h:
        req = urllib.request.Request(f"http://127.0.0.1:{h.port}/api")
        req.add_header("Host", "evil.example.com")
        try:
            urllib.request.urlopen(req, timeout=2)
        except urllib.error.HTTPError as e:
            assert e.code == 403
            return
        pytest.fail("expected 403 for bad Host")


def test_api_accepts_localhost_host():
    with _Harness() as h:
        req = urllib.request.Request(f"http://127.0.0.1:{h.port}/api")
        req.add_header("Host", f"localhost:{h.port}")
        try:
            r = urllib.request.urlopen(req, timeout=2)
            assert r.status == 200
        except urllib.error.HTTPError as e:
            assert e.code != 403, f"localhost Host should be allowed, got {e.code}"


def test_api_accepts_127_host():
    with _Harness() as h:
        req = urllib.request.Request(f"http://127.0.0.1:{h.port}/api")
        req.add_header("Host", f"127.0.0.1:{h.port}")
        try:
            r = urllib.request.urlopen(req, timeout=2)
            assert r.status == 200
        except urllib.error.HTTPError as e:
            assert e.code != 403


def test_home_page_no_host_check():
    """Home page doesn't check Host header (public)."""
    with _Harness() as h:
        req = urllib.request.Request(f"http://127.0.0.1:{h.port}/")
        req.add_header("Host", "evil.example.com")
        try:
            r = urllib.request.urlopen(req, timeout=2)
            assert r.status == 200
        except urllib.error.HTTPError as e:
            assert e.code != 403, f"home page should ignore Host, got {e.code}"


# --- Rate limiting --------------------------------------------------------

def test_rate_limit_rejects_excess_concurrent():
    """When all slots are taken, additional requests get a 'Server busy' event."""
    for _ in range(web.MAX_CONCURRENT_TRANSCRIPTIONS):
        web._transcription_slots.acquire()

    try:
        with _Harness() as h:
            r = h.get("/api?url=https://youtube.com/watch?v=zzz")
            assert r.status == 200  # SSE always returns 200
            body = r.read().decode()
            assert "Server busy" in body or "error" in body
    finally:
        for _ in range(web.MAX_CONCURRENT_TRANSCRIPTIONS):
            web._transcription_slots.release()


def test_rate_limit_allows_when_slots_free():
    """With free slots, the request proceeds (hits missing-url guard)."""
    with _Harness() as h:
        r = h.get("/api")
        assert r.status == 200
        data = json.loads(r.read().decode())
        assert "error" in data  # missing url error, NOT rate limit


# --- 404 ------------------------------------------------------------------

def test_unknown_path_returns_404():
    with _Harness() as h:
        r = h.get("/nonexistent")
        assert r.status == 404


# --- _allowed_origins helper ----------------------------------------------

def test_allowed_origins():
    origins = web._allowed_origins(8080)
    assert "http://localhost:8080" in origins
    assert "http://127.0.0.1:8080" in origins


def test_allowed_origins_different_port():
    assert web._allowed_origins(9090) != web._allowed_origins(8080)


# --- format and URL validation in API (#9, #21) ---------------------------

def test_api_rejects_invalid_format():
    with _Harness() as h:
        r = h.get("/api?url=https://youtube.com/watch?v=x&format=evil")
        assert r.status == 200
        data = json.loads(r.read().decode())
        assert "Invalid format" in data.get("error", "")


def test_api_rejects_non_youtube_url():
    with _Harness() as h:
        r = h.get("/api?url=https://example.com/")
        assert r.status == 200
        data = json.loads(r.read().decode())
        assert "Not a YouTube URL" in data.get("error", "")
