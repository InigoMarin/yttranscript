"""yt-dlp wrappers and dependency management."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .log import info, success, error, warn, debug
from .util import run, command_exists, confirm, sanitize_filename, TranscriptError

# Sensible per-call subprocess timeouts (seconds). They are safety nets to
# avoid hanging forever on network stalls — generous enough to not interfere
# with legitimate use. yt-dlp/whisper themselves also have their own retries.
TIMEOUT_METADATA = 60.0     # --print title/language/info
TIMEOUT_SUBTITLE = 120.0    # subtitle download
TIMEOUT_LIST_SUBS = 60.0    # --list-subs
TIMEOUT_CHANNEL = 120.0     # --latest channel fetch
TIMEOUT_AUDIO_DOWNLOAD = 1800.0  # 30 min for very long / high-bitrate audios
TIMEOUT_PIP_INSTALL = 600.0  # openai-whisper is ~1-3 GB


def ensure_yt_dlp() -> None:
    """Ensure yt-dlp is installed."""
    if command_exists("yt-dlp"):
        return

    info("yt-dlp not found, installing...")
    try:
        if command_exists("pipx"):
            result = run(["pipx", "install", "yt-dlp"],
                         capture=True, check=False, timeout=TIMEOUT_PIP_INSTALL)
            if result.returncode == 0:
                # pipx installs into ~/.local/bin which may not yet be on PATH
                # for this shell session; extend PATH so the binary is usable now.
                _ensure_local_bin_on_path()
                if command_exists("yt-dlp"):
                    success("yt-dlp installed")
                    return
                raise TranscriptError(
                    "pipx installed yt-dlp but it is not on your PATH. "
                    "Reopen your shell or add ~/.local/bin to PATH, then rerun."
                )
            warn("pipx install failed, trying alternatives...")
            if result.stderr.strip():
                debug(f"pipx stderr: {result.stderr.strip()}")

        try:
            run([sys.executable, "-m", "pip", "--version"],
                capture=True, check=True, timeout=30)
            pip_available = True
        except Exception:
            pip_available = False

        if pip_available:
            result = run([sys.executable, "-m", "pip", "install", "yt-dlp"],
                         capture=True, check=False, timeout=TIMEOUT_PIP_INSTALL)
            if result.returncode == 0:
                if command_exists("yt-dlp"):
                    success("yt-dlp installed")
                    return
            else:
                warn("pip install failed, trying alternatives...")
                if result.stderr.strip():
                    debug(f"pip stderr: {result.stderr.strip()}")

        if command_exists("brew"):
            if confirm("Install yt-dlp via Homebrew?"):
                run(["brew", "install", "yt-dlp"], timeout=TIMEOUT_PIP_INSTALL)
        elif command_exists("apt"):
            if confirm("Install yt-dlp via apt? This requires your sudo password."):
                run(["sudo", "apt", "update"], timeout=120)
                run(["sudo", "apt", "install", "-y", "yt-dlp"], timeout=TIMEOUT_PIP_INSTALL)
    except subprocess.TimeoutExpired:
        raise TranscriptError(
            "yt-dlp installation timed out. Install manually: "
            "https://github.com/yt-dlp/yt-dlp#installation"
        )

    if not command_exists("yt-dlp"):
        raise TranscriptError(
            "Failed to install yt-dlp. Install manually: "
            "https://github.com/yt-dlp/yt-dlp#installation"
        )
    success("yt-dlp installed")


def _ensure_local_bin_on_path() -> None:
    """Prepend ~/.local/bin to PATH for this process if not already present.

    pipx installs CLI binaries there; on first install in a long-lived shell
    that directory may not yet be on PATH. Mutates os.environ['PATH'] in place.
    """
    local_bin = str(Path.home() / ".local" / "bin")
    current = os.environ.get("PATH", "")
    if local_bin not in current.split(os.pathsep):
        os.environ["PATH"] = f"{local_bin}{os.pathsep}{current}"


def ensure_whisper() -> bool:
    """Ensure Whisper is installed. Returns True if available or installed."""
    if command_exists("whisper"):
        return True

    if not confirm("Whisper is not installed. Install openai-whisper (~1-3 GB)?"):
        return False

    info("Installing openai-whisper...")
    try:
        run(
            [sys.executable, "-m", "pip", "install", "openai-whisper"],
            timeout=TIMEOUT_PIP_INSTALL,
        )
    except subprocess.CalledProcessError:
        error("Failed to install openai-whisper. Try: pip install openai-whisper")
        return False
    except subprocess.TimeoutExpired:
        error("openai-whisper installation timed out. Try: pip install openai-whisper")
        return False

    return command_exists("whisper")


def get_video_metadata(url: str) -> dict:
    """Fetch all video metadata in a single yt-dlp -j call.

    Consolidates language detection, title, duration and size into one
    subprocess invocation instead of three separate ones.

    Returns dict with keys:
        title, sanitized_title, duration, size, language.
    """
    result = run(
        ["yt-dlp", "-j", "-f", "bestaudio", url],
        capture=True, check=False, timeout=TIMEOUT_METADATA,
    )
    fallback = {
        "title": "unknown",
        "sanitized_title": "transcript",
        "duration": 0,
        "size": 0,
        "language": None,
        "channel": "",
        "upload_date": "",
        "is_live": False,
    }
    if result.returncode != 0:
        return fallback
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return fallback

    title = data.get("title") or "unknown"

    duration = 0
    raw_duration = data.get("duration")
    if raw_duration is not None:
        try:
            duration = int(float(raw_duration))
        except (ValueError, TypeError):
            pass

    size = 0
    raw_size = data.get("filesize_approx") or data.get("filesize")
    if raw_size is not None:
        try:
            size = int(float(raw_size))
        except (ValueError, TypeError):
            pass

    language = data.get("language")
    if not language or language == "NA":
        language = None
    elif "-" in language:
        language = language.split("-")[0]

    channel = data.get("channel") or data.get("uploader") or ""

    upload_date_raw = data.get("upload_date") or ""
    upload_date = _parse_upload_date(upload_date_raw)

    is_live = data.get("is_live") or data.get("live_status") == "is_live"

    return {
        "title": title,
        "sanitized_title": sanitize_filename(title),
        "duration": duration,
        "size": size,
        "language": language,
        "channel": channel,
        "upload_date": upload_date,
        "is_live": is_live,
    }


def list_subs(url: str) -> None:
    """List available subtitles for the video."""
    info("Available subtitles:")
    run(["yt-dlp", "--list-subs", url], check=False, timeout=TIMEOUT_LIST_SUBS)


def resolve_channel_videos(url: str, limit: int = 10) -> tuple[str, list[tuple[str, str, str]]]:
    """Resolve a channel URL and return its latest videos.

    Returns a tuple of (channel_name, [(date_str, video_id, title), ...]).
    """
    info(f"Resolving channel from: {url}")
    result = run(
        ["yt-dlp", "--print", "%(channel_id)s|%(channel)s", "--playlist-items", "1", url],
        capture=True, check=False, quiet=True, timeout=TIMEOUT_METADATA,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise TranscriptError("Could not resolve channel ID from the provided URL.")

    first_line = result.stdout.strip().splitlines()[0]
    ch_parts = first_line.split("|", 1)
    channel_id = ch_parts[0]
    channel_name = ch_parts[1] if len(ch_parts) > 1 else channel_id
    if not channel_id.startswith("UC"):
        raise TranscriptError(f"Invalid channel ID: {channel_id}")

    uploads_playlist = "UU" + channel_id[2:]
    playlist_url = f"https://www.youtube.com/playlist?list={uploads_playlist}"
    success(f"Channel: {channel_name} ({channel_id})")

    info(f"Fetching latest {limit} videos...")
    fetch_limit = limit * 3
    result = run(
        ["yt-dlp", "--playlist-items", f"1-{fetch_limit}",
         "--print", "%(upload_date)s|%(id)s|%(title)s",
         "--no-abort-on-error",
         playlist_url],
        capture=True, check=False, quiet=True, timeout=TIMEOUT_CHANNEL,
    )
    videos: list[tuple[str, str, str]] = []
    for line in result.stdout.strip().splitlines():
        if line.startswith("ERROR"):
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        date_raw, vid, title = parts
        date_str = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}" if len(date_raw) == 8 and date_raw != "NA" else "Unknown"
        videos.append((date_str, vid, title))
    if not videos:
        raise TranscriptError("Could not fetch channel videos.")
    return channel_name, videos[:limit]


def list_channel_videos(url: str, limit: int = 10) -> tuple[str, list[tuple[str, str, str]]]:
    """List latest videos from a YouTube channel.

    Returns a tuple of (channel_name, [(date_str, video_id, title), ...]).
    """
    channel_name, videos = resolve_channel_videos(url, limit)
    info("")
    for date_str, vid, title in videos:
        info(f"Date: {date_str} | Title: {title} | URL: https://www.youtube.com/watch?v={vid}")
    info("")
    return channel_name, videos


def _parse_upload_date(raw: str) -> str:
    """Convert a yt-dlp YYYYMMDD date to ISO YYYY-MM-DD."""
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return ""


def get_video_info(url: str) -> dict:
    """Get basic video info."""
    fmt = "%(duration)s|%(filesize_approx)s|%(title)s|%(channel)s|%(upload_date)s"
    result = run(
        ["yt-dlp", "--print", fmt, "-f", "bestaudio", url],
        capture=True, check=False, timeout=TIMEOUT_METADATA,
    )
    if result.returncode != 0:
        warn("Could not fetch video info (duration/size will be unknown).")
        return {"duration": 0, "size": 0, "title": "unknown", "channel": "", "upload_date": ""}
    parts = result.stdout.strip().split("|", 4)
    try:
        duration = int(float(parts[0])) if len(parts) > 0 and parts[0] != "NA" else 0
    except ValueError:
        duration = 0
    try:
        size = int(float(parts[1])) if len(parts) > 1 and parts[1] != "NA" else 0
    except ValueError:
        size = 0
    title = parts[2] if len(parts) > 2 else "unknown"
    channel = parts[3] if len(parts) > 3 and parts[3] != "NA" else ""
    upload_date_raw = parts[4] if len(parts) > 4 and parts[4] != "NA" else ""
    upload_date = _parse_upload_date(upload_date_raw)
    return {"duration": duration, "size": size, "title": title, "channel": channel, "upload_date": upload_date}


def try_download_subtitle(
    url: str,
    output_prefix: str,
    lang: str,
    use_auto: bool = False,
    work_dir: Optional[Path] = None,
    try_both: bool = False,
) -> bool:
    """Attempt to download subtitles. Returns True on success.

    `output_prefix` may be relative (CWD) or absolute. When `work_dir` is given,
    it overrides the directory where the VTT is searched for (used when the
    caller passes an absolute prefix inside a tempdir).

    When `try_both` is True, both --write-sub and --write-auto-sub are passed,
    letting yt-dlp prefer manual subs and fall back to auto in a single call.
    """
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--output", output_prefix,
        "--sub-langs", lang,
    ]
    if try_both:
        cmd.extend(["--write-sub", "--write-auto-sub"])
    elif use_auto:
        cmd.append("--write-auto-sub")
    else:
        cmd.append("--write-sub")

    cmd.append(url)

    result = run(cmd, check=False, capture=True, timeout=TIMEOUT_SUBTITLE)
    if result.returncode != 0:
        return False

    # Check that a .vtt file was actually created in the expected location.
    search_dir = work_dir if work_dir is not None else Path(".")
    prefix_name = Path(output_prefix).name
    vtt_files = list(search_dir.glob(f"{prefix_name}*.vtt"))
    return len(vtt_files) > 0


def get_lang_variants(lang: str) -> list[str]:
    """Generate language code variants to try for subtitle download.

    Tries the wildcard pattern first (catches YouTube-specific variants
    like es-orig, es-en, etc.), then the exact code as fallback.
    """
    base = lang.split("-")[0]
    if base != lang:
        return [f"{base}.*", lang, base]
    return [f"{lang}.*", lang]
