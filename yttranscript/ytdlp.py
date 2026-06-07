"""yt-dlp wrappers and dependency management."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from .log import info, success, error, warn
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
        try:
            run([sys.executable, "-m", "pip", "--version"],
                capture=True, check=True, timeout=30)
            pip_available = True
        except Exception:
            pip_available = False

        if pip_available:
            try:
                run([sys.executable, "-m", "pip", "install", "yt-dlp"],
                    timeout=TIMEOUT_PIP_INSTALL)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                warn("pip install failed, trying alternatives...")
            else:
                if command_exists("yt-dlp"):
                    success("yt-dlp installed")
                    return

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


def _sanitize_filename(title: str) -> str:
    """Backwards-compatible alias for util.sanitize_filename."""
    return sanitize_filename(title)


def get_video_title(url: str) -> str:
    """Get video title and sanitize for filesystem."""
    result = run(
        ["yt-dlp", "--print", "%(title)s", url],
        capture=True, check=False, timeout=TIMEOUT_METADATA,
    )
    title = result.stdout.strip() if result.returncode == 0 else "transcript"
    return sanitize_filename(title)


def list_subs(url: str) -> None:
    """List available subtitles for the video."""
    info("Available subtitles:")
    run(["yt-dlp", "--list-subs", url], check=False, timeout=TIMEOUT_LIST_SUBS)


def resolve_channel_videos(url: str, limit: int = 10) -> list[tuple[str, str, str]]:
    """Resolve a channel URL and return its latest videos.

    Returns a list of (date_str, video_id, title) tuples.
    """
    info(f"Resolving channel from: {url}")
    result = run(
        ["yt-dlp", "--print", "%(channel_id)s", "--playlist-items", "1", url],
        capture=True, check=False, quiet=True, timeout=TIMEOUT_METADATA,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise TranscriptError("Could not resolve channel ID from the provided URL.")

    channel_id = result.stdout.strip().splitlines()[0]
    if not channel_id.startswith("UC"):
        raise TranscriptError(f"Invalid channel ID: {channel_id}")

    uploads_playlist = "UU" + channel_id[2:]
    playlist_url = f"https://www.youtube.com/playlist?list={uploads_playlist}"
    success(f"Channel: {channel_id}")

    info(f"Fetching latest {limit} videos...")
    result = run(
        ["yt-dlp", "--playlist-items", f"1-{limit}",
         "--print", "%(upload_date)s|%(id)s|%(title)s",
         playlist_url],
        capture=True, check=False, timeout=TIMEOUT_CHANNEL,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise TranscriptError("Could not fetch channel videos.")

    videos: list[tuple[str, str, str]] = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        date_raw, vid, title = parts
        date_str = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}" if len(date_raw) == 8 and date_raw != "NA" else "Unknown"
        videos.append((date_str, vid, title))
    return videos


def list_channel_videos(url: str, limit: int = 10) -> list[tuple[str, str, str]]:
    """List latest videos from a YouTube channel.

    Returns the list of (date_str, video_id, title) tuples (also printed).
    """
    videos = resolve_channel_videos(url, limit)
    info("")
    for date_str, vid, title in videos:
        info(f"Date: {date_str} | Title: {title} | URL: https://www.youtube.com/watch?v={vid}")
    info("")
    return videos


def get_video_info(url: str) -> dict:
    """Get basic video info."""
    fmt = "%(duration)s|%(filesize_approx)s|%(title)s"
    result = run(
        ["yt-dlp", "--print", fmt, "-f", "bestaudio", url],
        capture=True, check=False, timeout=TIMEOUT_METADATA,
    )
    if result.returncode != 0:
        warn("Could not fetch video info (duration/size will be unknown).")
        return {"duration": 0, "size": 0, "title": "unknown"}
    parts = result.stdout.strip().split("|", 2)
    try:
        duration = int(float(parts[0])) if len(parts) > 0 and parts[0] != "NA" else 0
    except ValueError:
        duration = 0
    try:
        size = int(float(parts[1])) if len(parts) > 1 and parts[1] != "NA" else 0
    except ValueError:
        size = 0
    title = parts[2] if len(parts) > 2 else "unknown"
    return {"duration": duration, "size": size, "title": title}


def try_download_subtitle(
    url: str,
    output_prefix: str,
    lang: str,
    use_auto: bool,
    work_dir: Optional[Path] = None,
) -> bool:
    """Attempt to download subtitles. Returns True on success.

    `output_prefix` may be relative (CWD) or absolute. When `work_dir` is given,
    it overrides the directory where the VTT is searched for (used when the
    caller passes an absolute prefix inside a tempdir).
    """
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--output", output_prefix,
        "--sub-langs", lang,
    ]
    if use_auto:
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


def detect_video_language(url: str) -> Optional[str]:
    """Detect video language using yt-dlp. Returns None if detection fails."""
    result = run(
        ["yt-dlp", "--print", "%(language)s", url],
        capture=True, check=False, timeout=TIMEOUT_METADATA,
    )
    if result.returncode != 0:
        return None
    lang = result.stdout.strip()
    if not lang or lang == "NA":
        return None
    # Normalize: "en-US" → "en"
    return lang.split("-")[0]


def get_lang_variants(lang: str) -> list[str]:
    """Generate language code variants to try for subtitle download.

    Tries the exact code first, then falls back to a wildcard pattern
    to catch YouTube-specific variants like es-orig, es-en, etc.
    """
    base = lang.split("-")[0]
    if base != lang:
        return [lang, base, f"{base}.*"]
    return [lang, f"{lang}.*"]
