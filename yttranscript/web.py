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

from .log import success, warn, ThreadLocalStdout, stdout_capture
from .config import load_config, resolve_value
from .util import sanitize_filename, TranscriptError
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


WEB_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>yttranscript</title>
<style>
  :root { --bg: #0f0f0f; --surface: #1a1a2e; --accent: #7c3aed; --text: #e2e8f0; --muted: #94a3b8; --ok: #22c55e; --err: #ef4444; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; justify-content: center; padding: 2rem; }
  .container { max-width: 800px; width: 100%; }
  h1 { font-size: 1.5rem; margin-bottom: 1.5rem; color: var(--accent); }
  .card { background: var(--surface); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; }
  input[type="text"] { width: 100%; padding: 0.75rem 1rem; border-radius: 8px; border: 1px solid #334155; background: #0f0f0f; color: var(--text); font-size: 1rem; }
  input[type="text"]:focus { outline: none; border-color: var(--accent); }
  .row { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 1rem; align-items: center; }
  select, input[type="checkbox"] { accent-color: var(--accent); }
  select { padding: 0.5rem; border-radius: 6px; background: #0f0f0f; color: var(--text); border: 1px solid #334155; }
  .lang-input { width: 5rem; padding: 0.35rem 0.5rem; border-radius: 6px; background: #0f0f0f; color: var(--text); border: 1px solid #334155; font-size: 0.875rem; }
  label { font-size: 0.875rem; color: var(--muted); display: flex; align-items: center; gap: 0.25rem; }
  button { padding: 0.75rem 2rem; border-radius: 8px; border: none; background: var(--accent); color: white; font-size: 1rem; font-weight: 600; cursor: pointer; transition: opacity 0.2s; }
  button:hover { opacity: 0.85; }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  #status { margin-top: 1rem; font-size: 0.875rem; color: var(--muted); }
  #result { font-size: 0.875rem; line-height: 1.6; max-height: 60vh; overflow-y: auto; padding: 0.25rem; }
  #result.plain { white-space: pre-wrap; font-family: monospace; }
  #result.md { font-family: system-ui, sans-serif; }
  #result.md h1 { font-size: 1.3rem; margin: 0 0 0.75rem; color: var(--accent); }
  #result.md h2 { font-size: 1.15rem; margin: 0.75rem 0 0.4rem; }
  #result.md h3 { font-size: 1rem; margin: 0.6rem 0 0.35rem; color: var(--text); }
  #result.md p { margin: 0.35rem 0; }
  #result.md strong { font-weight: 700; }
  #result.md hr { border: none; border-top: 1px solid #334155; margin: 0.75rem 0; }
  #result.md ul { margin: 0.35rem 0 0.35rem 1.5rem; }
  #result.md li { margin: 0.15rem 0; }
  .error { color: var(--err); }
  .ok { color: var(--ok); }
  #log { max-height: 180px; overflow-y: auto; margin-top: 0.75rem; font-size: 0.8rem; font-family: monospace; display: none; }
  .log-info { color: var(--muted); }
  .log-success { color: var(--ok); }
  .log-warn { color: #fbbf24; }
  .log-error { color: var(--err); }
  #download-row { display: none; margin-top: 0.75rem; gap: 0.5rem; }
  button.cancel { background: var(--err); }
  .spinner { display: inline-block; width: 1rem; height: 1rem; border: 2px solid var(--muted); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="container">
  <h1>&#9733; yttranscript</h1>
  <div class="card">
    <input type="text" id="url" placeholder="Paste YouTube URL..." />
    <div class="row">
      <label>Lang <input type="text" id="lang" list="lang-codes" placeholder="Auto" class="lang-input"><datalist id="lang-codes"><option value="en"><option value="es"><option value="fr"><option value="de"><option value="pt"><option value="it"><option value="ja"><option value="zh"><option value="ko"><option value="ar"><option value="ru"><option value="nl"><option value="pl"><option value="tr"></datalist></label>
      <label>Format <select id="format"><option value="txt">txt</option><option value="json">json</option><option value="vtt">vtt</option></select></label>
      <label><input type="checkbox" id="timestamps"> Timestamps</label>
      <label><input type="checkbox" id="summarize"> Summarize</label>
    </div>
    <div class="row">
      <button id="btn" onclick="run()">Transcribe</button>
      <div id="download-row">
        <button onclick="copyText()" id="copy-btn">Copy</button>
        <button onclick="downloadFile()" id="dl-btn">Download</button>
      </div>
    </div>
    <div id="status"></div>
    <div id="log"></div>
  </div>
  <div class="card" id="output-card" style="display:none;">
    <div id="result"></div>
  </div>
</div>
<script>
let lastResult = null;
let currentController = null;
function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function inlineMd(s) {
  return s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
}
function renderMarkdown(text) {
  const t = escapeHtml(text);
  const blocks = t.split(/\n\n+/);
  const html = [];
  for (const block of blocks) {
    const lines = block.split('\n');
    const first = lines[0].trim();
    if (first === '---') { html.push('<hr>'); continue; }
    const hm = first.match(/^(#{1,3})\s+(.+)$/);
    if (hm) { html.push('<h' + hm[1].length + '>' + inlineMd(hm[2]) + '</h' + hm[1].length + '>'); continue; }
    if (first.match(/^[-*]\s/)) {
      const items = lines.filter(l => l.trim().match(/^[-*]\s/)).map(l =>
        '<li>' + inlineMd(l.trim().replace(/^[-*]\s/, '')) + '</li>');
      html.push('<ul>' + items.join('') + '</ul>');
      continue;
    }
    const joined = lines.map(l => l.endsWith('  ') ? l.slice(0,-2) + '<br>' : l).join(' ');
    html.push('<p>' + inlineMd(joined) + '</p>');
  }
  return html.join('\n');
}
function addLog(message, type) {
  const log = document.getElementById('log');
  log.style.display = 'block';
  const div = document.createElement('div');
  div.className = 'log-' + type;
  div.textContent = message;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}
function setStatus(text, cls) {
  const status = document.getElementById('status');
  status.textContent = '';
  const span = document.createElement('span');
  if (cls) span.className = cls;
  span.textContent = text;
  status.appendChild(span);
}
async function run() {
  const btn = document.getElementById('btn');
  if (currentController) {
    currentController.abort();
    return;
  }
  const url = document.getElementById('url').value.trim();
  if (!url) return;
  const status = document.getElementById('status');
  const result = document.getElementById('result');
  const outputCard = document.getElementById('output-card');
  const dlRow = document.getElementById('download-row');
  const log = document.getElementById('log');
  const fmt = document.getElementById('format').value;
  const summarize = document.getElementById('summarize').checked;
  log.innerHTML = '';
  log.style.display = 'none';
  result.textContent = '';
  outputCard.style.display = 'none';
  dlRow.style.display = 'none';
  setStatus('', '');
  status.innerHTML = '<span class="spinner"></span> Processing...';
  btn.textContent = 'Cancel';
  btn.className = 'cancel';
  const params = new URLSearchParams({ url });
  if (document.getElementById('lang').value) params.set('lang', document.getElementById('lang').value);
  params.set('format', fmt);
  if (document.getElementById('timestamps').checked) params.set('timestamps', '1');
  if (summarize) params.set('summarize', '1');
  const controller = new AbortController();
  currentController = controller;
  try {
    const res = await fetch('/api?' + params, { signal: controller.signal });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        if (!raw.startsWith('data: ')) continue;
        const data = JSON.parse(raw.slice(6));
        if (data.type === 'done') {
          setStatus(data.title, 'ok');
          outputCard.style.display = 'block';
          lastResult = { text: data.text, filename: data.filename || 'transcript.txt' };
          if ((fmt === 'txt' || summarize) && fmt !== 'json' && fmt !== 'vtt') {
            result.className = 'md';
            result.innerHTML = renderMarkdown(data.text);
          } else {
            result.className = 'plain';
            result.textContent = data.text;
          }
          dlRow.style.display = 'flex';
        } else if (data.type === 'error') {
          setStatus(data.message, 'error');
        } else {
          addLog(data.message, data.type);
        }
      }
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      setStatus('Cancelled.', 'error');
    } else {
      setStatus('Request failed: ' + e.message, 'error');
    }
  }
  currentController = null;
  btn.textContent = 'Transcribe';
  btn.className = '';
}
document.getElementById('url').addEventListener('keydown', e => { if (e.key === 'Enter') run(); });
async function copyText() {
  const result = document.getElementById('result');
  const text = result.className === 'md' ? result.innerText : result.textContent;
  if (!text) return;
  await navigator.clipboard.writeText(text);
  const btn = document.getElementById('copy-btn');
  btn.textContent = 'Copied!';
  setTimeout(() => btn.textContent = 'Copy', 1500);
}
function downloadFile() {
  if (!lastResult) return;
  const ext = lastResult.filename.split('.').pop();
  const mime = ext === 'json' ? 'application/json' : ext === 'vtt' ? 'text/vtt' : 'text/plain';
  const blob = new Blob([lastResult.text], { type: mime + ';charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = lastResult.filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
</script>
</body>
</html>"""


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
        self.wfile.write(WEB_HTML.encode("utf-8"))

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
        fmt = params.get("format", ["txt"])[0]
        if fmt not in ("txt", "json", "vtt"):
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
        ext = {"json": ".json", "txt": ".txt", "vtt": ".vtt"}.get(fmt, ".txt")
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
