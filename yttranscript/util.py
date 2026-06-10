"""Small generic helpers used across modules."""

from __future__ import annotations

import re
import shutil
import subprocess

from . import log
from .log import debug


class TranscriptError(Exception):
    """Raised when transcript processing fails (bad URL, no subtitles, etc.).

    Caught by the CLI (prints + exit 1) and web handler (SSE error event).
    Replaces sys.exit() calls so the function is usable as a library.
    """


_YOUTUBE_URL_RE = re.compile(
    r"^https?://"
    r"(?:[a-z0-9-]+\.)*"
    r"(?:youtube\.com|youtu\.be|youtube-nocookie\.com)/",
    re.IGNORECASE,
)


_PLAYLIST_RE = re.compile(r"[?&]list=", re.IGNORECASE)


_LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


def is_youtube_url(url: str | None) -> bool:
    """Return True if `url` looks like a YouTube URL."""
    return bool(url) and bool(_YOUTUBE_URL_RE.match(url))


def is_playlist_url(url: str | None) -> bool:
    """Return True if `url` is a YouTube playlist URL (not a single video)."""
    return is_youtube_url(url) and bool(_PLAYLIST_RE.search(url or ""))


def is_valid_lang_code(lang: str | None) -> bool:
    """Return True if `lang` looks like a valid language code.

    Accepts 2-3 letter codes (e.g. 'es', 'en', 'ja') optionally followed by
    a region or script suffix (e.g. 'pt-BR', 'zh-Hans', 'en-US').
    """
    return bool(lang) and bool(_LANG_RE.match(lang))


def run(
    cmd: list[str],
    check: bool = True,
    capture: bool = False,
    quiet: bool = False,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run a command and optionally capture/suppress output.

    Raises subprocess.TimeoutExpired if `timeout` is set and exceeded.
    """
    debug(f"$ {' '.join(cmd)}")
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=timeout)
    if quiet or log.VERBOSITY == 0:
        return subprocess.run(
            cmd, check=check,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    return subprocess.run(cmd, check=check, timeout=timeout)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def confirm(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(f"{prompt}{suffix}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def format_duration(seconds: int | float) -> str:
    """Format seconds as human-readable duration (e.g. '1:23:45', '12:34').

    Returns 'unknown' for zero/falsy values.
    """
    seconds = int(seconds)
    if not seconds:
        return "unknown"
    hours = seconds // 3600
    if hours:
        return f"{hours}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def sanitize_filename(title: str) -> str:
    """Replace characters problematic in filenames and cap length."""
    for ch in '/:?\"<>|*':
        title = title.replace(ch, "-")
    title = title.strip().strip(".")
    if len(title) > 200:
        title = title[:200].rstrip()
    return title or "transcript"
