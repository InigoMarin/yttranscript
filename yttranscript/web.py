"""Local web UI server (HTTP + SSE).

Bound to 127.0.0.1 only. Each request runs in its own thread (via
ThreadingHTTPServer); per-thread log routing and stdout capture are set up
in `_serve_api` via the `log.stdout_capture` context manager and `core.process_video`
internally uses `log.log_context`.

Security:
  - Origin header check (CSRF protection): browsers send Origin on cross-site
    fetches; we reject anything that isn't localhost. Absent Origin (curl,
    direct navigation) is allowed.
  - Host header check (DNS rebinding protection): Host must be localhost or
    127.0.0.1.
  - Concurrency limit: a bounded semaphore caps simultaneous transcriptions to
    keep a single malicious / buggy client from exhausting resources.
"""

from __future__ import annotations

import io
import json
import sys
import threading
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from .log import success, warn, ThreadLocalStdout, stdout_capture
from .config import load_config, resolve_value
from .util import sanitize_filename, TranscriptError, is_valid_lang_code
from .core import process_video


# Cap concurrent /api transcriptions. Each one spawns yt-dlp (+ possibly
# Whisper), so unbounded concurrency is a trivial DoS vector. 2 lets the user
# have a couple of tabs open without blocking.
MAX_CONCURRENT_TRANSCRIPTIONS = 2
_transcription_slots = threading.BoundedSemaphore(MAX_CONCURRENT_TRANSCRIPTIONS)

# Hostnames we consider "local" for Origin/Host checks.
_LOCAL_HOSTNAMES = ("localhost", "127.0.0.1")


def _allowed_origins(port: int) -> set[str]:
    return {f"http://localhost:{port}", f"http://127.0.0.1:{port}"}


_WEB_HTML = (Path(__file__).parent / "web_ui.html").read_text(encoding="utf-8")


class TranscriptHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the web UI."""

    # Use a per-server lock-free check: server_address tells us the port.
    @property
    def _port(self) -> int:
        return self.server.server_address[1]

    def log_message(self, fmt, *args):
        from . import log
        if log.VERBOSITY >= 2:
            super().log_message(fmt, *args)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # Home page is public; the API gets the security checks.
        if parsed.path in ("/", "/index.html"):
            self._serve_html()
            return

        if parsed.path == "/api":
            # CSRF + DNS rebinding guards. Browsers send Origin on cross-site
            # requests; we accept absent Origin (curl, direct nav) but reject
            # anything that doesn't look like localhost. The Host check blocks
            # DNS-rebinding attacks where a public hostname resolves to 127.0.0.1.
            if not self._check_host():
                return
            if not self._check_origin():
                return
            self._serve_api(parsed.query)
            return

        self.send_error(404)

    def _check_host(self) -> bool:
        """DNS rebinding guard. Host header must resolve to localhost/127.0.0.1."""
        host = self.headers.get("Host", "")
        hostname = host.split(":")[0].lower()
        if hostname in _LOCAL_HOSTNAMES:
            return True
        self.send_error(403, "Refused: Host header is not localhost")
        return False

    def _check_origin(self) -> bool:
        """CSRF guard. Reject cross-origin browser requests.

        Browsers send Origin on cross-site fetches; we accept absent Origin
        (curl, server-side scripts, direct navigation) for compatibility, but
        reject any explicit Origin that isn't localhost.
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # curl, direct navigation, non-browser
        if origin in _allowed_origins(self._port):
            return True
        self.send_error(403, "Refused: cross-origin request blocked")
        return False

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_WEB_HTML.encode("utf-8"))

    def _serve_api(self, query_string):
        params = urllib.parse.parse_qs(query_string)
        url = params.get("url", [None])[0]
        if not url:
            self._json_response({"error": "Missing url parameter"})
            return

        from .util import is_youtube_url

        if not is_youtube_url(url):
            self._json_response({"error": "Not a YouTube URL"})
            return

        lang = params.get("lang", [None])[0]
        if lang and not is_valid_lang_code(lang):
            self._json_response({"error": f"Invalid language code: {lang}"})
            return
        fmt = params.get("format", ["txt"])[0]
        if fmt not in ("txt", "json", "vtt", "srt", "epub", "docx"):
            self._json_response({"error": f"Invalid format: {fmt}"})
            return
        timestamps = params.get("timestamps", ["0"])[0] == "1"
        summarize = params.get("summarize", ["0"])[0] == "1"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")  # disable proxy buffering
        self.end_headers()

        wfile = self.wfile

        def send_event(data: dict):
            wfile.write(f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            wfile.flush()

        # Rate limit: don't let one client exhaust resources.
        if not _transcription_slots.acquire(blocking=False):
            try:
                send_event({
                    "type": "error",
                    "message": (
                        f"Server busy: {MAX_CONCURRENT_TRANSCRIPTIONS} transcriptions "
                        f"already running. Please retry shortly."
                    ),
                })
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            self.close_connection = True
            return

        def log_callback(level: str, msg: str):
            send_event({"type": level, "message": msg})

        config = load_config()
        buf = io.StringIO()

        title = "transcript"
        try:
            with stdout_capture(buf):
                try:
                    title = process_video(
                        url=url,
                        fmt=fmt,
                        lang=lang,
                        timestamps=timestamps,
                        summarize=summarize,
                        summarize_cmd=resolve_value(None, config, "summarize_cmd"),
                        summarize_prompt=resolve_value(None, config, "summarize_prompt"),
                        summarize_timeout=resolve_value(None, config, "summarize_timeout"),
                        fallback_lang=resolve_value(None, config, "fallback_lang"),
                        stdout_mode=True,
                        log_callback=log_callback,
                    ) or "transcript"
                except (BrokenPipeError, ConnectionResetError, OSError):
                    self.close_connection = True
                    return
                except TranscriptError as e:
                    try:
                        send_event({"type": "error", "message": str(e)})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    self.close_connection = True
                    return
                except Exception as e:
                    try:
                        send_event({"type": "error", "message": str(e)})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    self.close_connection = True
                    return
        finally:
            _transcription_slots.release()

        text = buf.getvalue()
        ext = {
            "json": ".json", "txt": ".txt", "vtt": ".vtt", "srt": ".srt",
            "epub": ".epub", "docx": ".docx",
        }.get(fmt, ".txt")
        filename = sanitize_filename(title) + ext

        try:
            send_event({"type": "done", "text": text, "title": title, "filename": filename})
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        self.close_connection = True

    def _json_response(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(port: int) -> None:
    """Start the local web server."""
    original_stdout = sys.stdout
    sys.stdout = ThreadLocalStdout(original_stdout)
    server = ThreadingHTTPServer(("127.0.0.1", port), TranscriptHandler)
    success(f"Web UI: http://localhost:{port}")
    success("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        warn("Server stopped.")
        server.server_close()
    finally:
        sys.stdout = original_stdout
