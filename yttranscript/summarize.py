"""Summarization via external command piping or HTTP API.

Two backends, selected by ``backend``:

- ``cmd``: pipe transcript to an external command (default). Currently tailored
  to llama.cpp's ``llama-cli`` output format. Other tools may work but the
  response parsing is shaped around llama-cli's banner/prompt/stats structure.
- ``api``: POST transcript to an OpenAI-compatible chat completions endpoint
  (OpenAI, OpenRouter, LM Studio server, vLLM, Ollama HTTP, Groq, Together,
  ...). Uses stdlib ``urllib`` only — no extra dependencies.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from .log import info, debug, error


def summarize_text(text: str, cmd: str, prompt: str, timeout: int = 300) -> Optional[str]:
    """Send text to an external command for summarization.

    Uses `script` to capture all terminal output (including /dev/tty writes)
    into a temp file. Extracts only the model's response and cleans thinking.

    Returns the cleaned summary text on success, or None on failure.
    """
    if not cmd or not cmd.strip():
        error("Summarize command is empty.")
        return None

    full_input = f"{prompt} {text}"
    cmd_parts = shlex.split(cmd)
    cmd_parts = [os.path.expandvars(os.path.expanduser(p)) for p in cmd_parts]

    debug(f"$ echo '...' | {' '.join(cmd_parts[:4])}...")
    info("Summarizing... (this may take a while)")

    # Restrictive perms on temp files containing the transcript text.
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    tmp_path = tmp.name
    tmp.close()
    os.chmod(tmp_path, 0o600)

    input_tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    input_tmp.write(full_input)
    input_tmp.close()
    os.chmod(input_tmp.name, 0o600)

    try:
        escaped_cmd = ' '.join(shlex.quote(p) for p in cmd_parts)
        shell_cmd = f"cat {shlex.quote(input_tmp.name)} | {escaped_cmd}"

        try:
            result = subprocess.run(
                ['script', '-qec', shell_cmd, tmp_path],
                input='',
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            error(f"Summarize command timed out after {timeout} seconds.")
            return None
        except FileNotFoundError:
            error(f"Summarize command not found: '{cmd_parts[0]}'. Is it installed and on your PATH?")
            return None

        if result.returncode != 0:
            error(f"Summarize command failed (exit code {result.returncode}). Check your --summarize-cmd configuration.")
            return None

        raw = Path(tmp_path).read_text()

        # script prepends a header line and wraps output; strip ANSI/control chars
        output = raw.replace('\r', '').strip()
        output = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output)

        if not output:
            error("Summarize command produced no output.")
            return None

        # llama-cli output structure:
        #   [banner, loading, commands...]
        #   > <full prompt>         ← prompt echo (can be very long)
        #   [model response]        ← what we want
        #   [ Prompt: ... ]         ← stats
        #   Exiting...
        lines = output.split("\n")
        response_lines = []
        in_response = False
        for line in lines:
            if not in_response:
                if line.startswith("> "):
                    in_response = True
                continue
            if line.startswith("[ Prompt:") or line.startswith("Exiting"):
                break
            response_lines.append(line)

        clean = "\n".join(response_lines).strip()
        clean = clean.replace("\x08", "")
        clean = re.sub(r"^[|/\\-]+\s*", "", clean, flags=re.MULTILINE)
        clean = re.sub(r"\[Start thinking\].*?\[End thinking\]", "", clean, flags=re.DOTALL)
        clean = re.sub(r"\[Start thinking\].*$", "", clean, flags=re.DOTALL)
        clean = clean.strip()

        return clean if clean else output
    finally:
        os.unlink(tmp_path)
        os.unlink(input_tmp.name)


def summarize_text_api(
    text: str,
    api_url: str,
    api_model: str,
    api_key: str,
    prompt: str,
    timeout: int = 300,
) -> Optional[str]:
    """Send text to an OpenAI-compatible chat completions endpoint.

    Works with any provider implementing ``POST {api_url}`` returning the
    standard ``choices[0].message.content`` structure (OpenAI, OpenRouter,
    LM Studio server, vLLM, Ollama HTTP, Groq, Together, ...).

    Returns the cleaned summary text on success, or None on failure.
    """
    if not api_url or not api_url.strip():
        error("Summarize API URL is empty.")
        return None
    if not api_key:
        error("Summarize API key is empty (env var not set).")
        return None
    if not api_model:
        error("Summarize API model is empty.")
        return None

    full_prompt = f"{prompt} {text}" if prompt else text
    payload = {
        "model": api_model,
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0.3,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        api_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    debug(f"POST {api_url} (model={api_model}, {len(text)} chars)")
    info("Summarizing via API... (this may take a while)")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace").strip()[:300]
        except Exception:
            pass
        suffix = f" — {detail}" if detail else ""
        error(f"API returned HTTP {e.code}: {e.reason}{suffix}")
        return None
    except socket.timeout:
        error(f"API request timed out after {timeout} seconds.")
        return None
    except urllib.error.URLError as e:
        error(f"API request failed: {e.reason}")
        return None

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        error("API returned malformed JSON.")
        return None

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        error("Unexpected API response structure.")
        debug(f"Response: {raw[:300]!r}")
        return None

    clean = (content or "").strip()
    return clean if clean else None


def summarize(
    text: str,
    *,
    backend: str,
    cmd: Optional[str] = None,
    prompt: str = "",
    timeout: int = 300,
    api_url: Optional[str] = None,
    api_model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """Dispatch summarization to the selected backend.

    ``backend``: ``"cmd"`` (pipe to external command) or ``"api"``
    (OpenAI-compatible HTTP endpoint).
    """
    if backend == "api":
        return summarize_text_api(
            text, api_url or "", api_model or "", api_key or "", prompt, timeout
        )
    return summarize_text(text, cmd or "", prompt, timeout)


def derive_models_url(api_url: str) -> str:
    """Derive the ``GET /models`` endpoint from a chat completions URL.

    Standard OpenAI-compatible layout::

        {base}/chat/completions  ->  {base}/models

    Falls back to appending ``/models`` when the URL does not end with the
    standard suffix (so a base URL like ``https://api.openai.com/v1`` also
    works).
    """
    suffix = "/chat/completions"
    if api_url.endswith(suffix):
        return api_url[: -len(suffix)] + "/models"
    return api_url.rstrip("/") + "/models"


def list_models(
    api_url: str,
    api_key: str,
    timeout: int = 300,
) -> Optional[list[dict]]:
    """Fetch the list of accessible models from an OpenAI-compatible API.

    Returns a list of ``{"id", "owned_by", "created"}`` dicts sorted by id,
    or None on failure.
    """
    if not api_url or not api_url.strip():
        error("Summarize API URL is empty.")
        return None
    if not api_key:
        error("Summarize API key is empty (env var not set).")
        return None

    models_url = derive_models_url(api_url)
    req = urllib.request.Request(
        models_url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )

    debug(f"GET {models_url}")
    info("Fetching accessible models...")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace").strip()[:300]
        except Exception:
            pass
        suffix_detail = f" — {detail}" if detail else ""
        error(f"API returned HTTP {e.code}: {e.reason}{suffix_detail}")
        return None
    except socket.timeout:
        error(f"API request timed out after {timeout} seconds.")
        return None
    except urllib.error.URLError as e:
        error(f"API request failed: {e.reason}")
        return None

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        error("API returned malformed JSON.")
        return None

    entries = data.get("data", []) if isinstance(data, dict) else []
    models = [
        {
            "id": m.get("id", "?"),
            "owned_by": m.get("owned_by", "?"),
            "created": m.get("created"),
        }
        for m in entries
        if isinstance(m, dict)
    ]
    models.sort(key=lambda m: str(m["id"]))
    return models
