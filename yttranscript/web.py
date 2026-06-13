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
import secrets
import sys
import tempfile
import threading
import time
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

_BINARY_FORMATS = {"pdf", "epub", "docx"}

_DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "yttranscript-downloads"
_DOWNLOAD_TTL = 600

_downloads_lock = threading.Lock()
_downloads: dict[str, tuple[str, float]] = {}


def _cleanup_downloads():
    now = time.time()
    with _downloads_lock:
        expired = [k for k, (_, ts) in _downloads.items() if now - ts > _DOWNLOAD_TTL]
        for k in expired:
            path, _ = _downloads.pop(k)
            Path(path).unlink(missing_ok=True)


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
            if not self._check_host():
                return
            if not self._check_origin():
                return
            self._serve_api(parsed.query)
            return

        if parsed.path.startswith("/download/"):
            self._serve_download(parsed.path[len("/download/"):])
            return

        self.send_error(404)

    def _serve_download(self, download_id: str):
        _cleanup_downloads()
        with _downloads_lock:
            entry = _downloads.get(download_id)
        if not entry:
            self.send_error(404, "Download not found or expired")
            return
        path, _ = entry
        file_path = Path(path)
        if not file_path.exists():
            self.send_error(404, "File not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        with open(file_path, "rb") as f:
            self.wfile.write(f.read())

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
        if fmt not in ("txt", "json", "vtt", "srt", "pdf", "epub", "docx"):
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

        title = "transcript"
        try:
            if fmt in _BINARY_FORMATS:
                _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
                download_id = secrets.token_urlsafe(16)
                bin_dir = _DOWNLOAD_DIR / download_id
                bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

                try:
                    result = process_video(
                        url=url,
                        fmt=fmt,
                        lang=lang,
                        timestamps=timestamps,
                        summarize=summarize,
                        summarize_cmd=resolve_value(None, config, "summarize_cmd"),
                        summarize_prompt=resolve_value(None, config, "summarize_prompt"),
                        summarize_timeout=resolve_value(None, config, "summarize_timeout"),
                        fallback_lang=resolve_value(None, config, "fallback_lang"),
                        stdout_mode=False,
                        output_dir=str(bin_dir),
                        log_callback=log_callback,
                    )
                    if result:
                        title = result[0]
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

                ext = {"pdf": ".pdf", "epub": ".epub", "docx": ".docx"}[fmt]
                filename = sanitize_filename(title) + ext

                files = list(bin_dir.glob(f"*{ext}"))
                if not files:
                    try:
                        send_event({"type": "error", "message": "Failed to generate output file."})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    self.close_connection = True
                    return

                with _downloads_lock:
                    _downloads[download_id] = (str(files[0]), time.time())
                try:
                    send_event({
                        "type": "done",
                        "download": f"/download/{download_id}",
                        "title": title,
                        "filename": filename,
                    })
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            else:
                buf = io.StringIO()
                with stdout_capture(buf):
                    try:
                        result = process_video(
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
                        )
                        if result:
                            title = result[0]
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

                text = buf.getvalue()
                ext = {
                    "json": ".json", "txt": ".txt", "vtt": ".vtt", "srt": ".srt",
                }.get(fmt, ".txt")
                filename = sanitize_filename(title) + ext
                try:
                    send_event({"type": "done", "text": text, "title": title, "filename": filename})
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
        finally:
            _transcription_slots.release()

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
