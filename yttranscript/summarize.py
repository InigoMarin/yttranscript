"""Summarization via external command piping.

Currently tailored to llama.cpp's `llama-cli` output format. Other tools may
work but the response parsing is shaped around llama-cli's banner/prompt/stats
structure.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
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
