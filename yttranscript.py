#!/usr/bin/env python3
"""YouTube Transcript Downloader CLI.

Download transcripts (subtitles/captions) from YouTube videos.
Falls back to Whisper transcription when no subtitles are available.
"""

__version__ = "1.12.0"

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

CONFIG_PATH = Path.home() / ".config" / "yttranscript" / "config.toml"

DEFAULTS = {
    "lang": None,
    "format": "txt",
    "timestamps": False,
    "chunk_size": 30,
    "summarize_cmd": None,
    "summarize_prompt": "Summarize this video transcript in bullet points",
    "whisper_model": "base",
    "whisper_device": "gpu",
    "whisper_dir": None,
    "output": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VERBOSITY = 1  # 0=quiet, 1=normal, 2=verbose

class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def info(msg: str) -> None:
    if VERBOSITY >= 1:
        print(f"{Colors.BLUE}›{Colors.RESET} {msg}")


def success(msg: str) -> None:
    if VERBOSITY >= 1:
        print(f"{Colors.GREEN}✓{Colors.RESET} {msg}")


def warn(msg: str) -> None:
    if VERBOSITY >= 1:
        print(f"{Colors.YELLOW}⚠{Colors.RESET} {msg}")


def error(msg: str) -> None:
    print(f"{Colors.RED}✗{Colors.RESET} {msg}", file=sys.stderr)


def debug(msg: str) -> None:
    if VERBOSITY >= 2:
        print(f"{Colors.BLUE}𝒹{Colors.RESET} {msg}", file=sys.stderr)


def run(cmd: list[str], check: bool = True, capture: bool = False, quiet: bool = False) -> subprocess.CompletedProcess:
    """Run a command and optionally capture/suppress output."""
    debug(f"$ {' '.join(cmd)}")
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=check)
    if quiet or VERBOSITY == 0:
        return subprocess.run(cmd, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.run(cmd, check=check)


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


DEFAULT_CONFIG = """\
# yttranscript configuration
# Uncomment and edit the lines below to set your defaults.
# CLI flags always override these values.

# lang = "es"
# format = "txt"
# timestamps = true
# chunk_size = 30
# summarize_cmd = "llama-cli -m ~/.local/share/models/model.gguf --temp 0.7 -n 1024"
# summarize_prompt = "Summarize this video in bullet points"
# whisper_model = "base"
# whisper_device = "gpu"
# whisper_dir = "/home/user/.cache/whisper"
"""


def ensure_config_dir() -> None:
    """Create config directory and default config file on first run."""
    config_dir = CONFIG_PATH.parent
    if not config_dir.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG, encoding="utf-8")


def load_config() -> dict:
    """Load config from ~/.config/yttranscript/config.toml."""
    ensure_config_dir()
    if tomllib is None:
        return {}
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        warn(f"Could not parse config file ({CONFIG_PATH}): {e}")
        return {}


def resolve_value(arg_value, config: dict, key: str):
    """Resolve a value: CLI arg > config > default."""
    if arg_value is not None:
        return arg_value
    return config.get(key, DEFAULTS.get(key))


def get_lang_variants(lang: str) -> list[str]:
    """Generate language code variants to try for subtitle download.

    Tries the exact code first, then falls back to a wildcard pattern
    to catch YouTube-specific variants like es-orig, es-en, etc.
    """
    base = lang.split("-")[0]
    if base != lang:
        return [lang, base, f"{base}.*"]
    return [lang, f"{lang}.*"]


def detect_video_language(url: str) -> str | None:
    """Detect video language using yt-dlp. Returns None if detection fails."""
    result = run(
        ["yt-dlp", "--print", "%(language)s", url],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    lang = result.stdout.strip()
    if not lang or lang == "NA":
        return None
    # Normalize: "en-US" → "en"
    return lang.split("-")[0]


# ---------------------------------------------------------------------------
# Dependency management
# ---------------------------------------------------------------------------

def ensure_yt_dlp() -> None:
    """Ensure yt-dlp is installed."""
    if command_exists("yt-dlp"):
        return

    info("yt-dlp not found, installing...")
    if command_exists("brew"):
        run(["brew", "install", "yt-dlp"])
    elif command_exists("apt"):
        run(["sudo", "apt", "update"])
        run(["sudo", "apt", "install", "-y", "yt-dlp"])
    else:
        run([sys.executable, "-m", "pip", "install", "yt-dlp"])

    if not command_exists("yt-dlp"):
        error("Failed to install yt-dlp. Install manually: https://github.com/yt-dlp/yt-dlp#installation")
        sys.exit(1)
    success("yt-dlp installed")


def ensure_whisper() -> bool:
    """Ensure Whisper is installed. Returns True if available or installed."""
    if command_exists("whisper"):
        return True

    if not confirm("Whisper is not installed. Install openai-whisper (~1-3 GB)?"):
        return False

    info("Installing openai-whisper...")
    try:
        run([sys.executable, "-m", "pip", "install", "openai-whisper"])
    except subprocess.CalledProcessError:
        error("Failed to install openai-whisper. Try: pip install openai-whisper")
        return False

    return command_exists("whisper")


# ---------------------------------------------------------------------------
# yt-dlp wrappers
# ---------------------------------------------------------------------------

def get_video_title(url: str) -> str:
    """Get video title and sanitize for filesystem."""
    result = run(
        ["yt-dlp", "--print", "%(title)s", url],
        capture=True,
        check=False,
    )
    title = result.stdout.strip() if result.returncode == 0 else "transcript"
    # Sanitize: replace problematic characters
    for ch in "/:?\"<>|*":
        title = title.replace(ch, "-")
    return title or "transcript"


def list_subs(url: str) -> None:
    """List available subtitles for the video."""
    info(f"Available subtitles for:")
    run(["yt-dlp", "--list-subs", url], check=False)


def get_video_info(url: str) -> dict:
    """Get basic video info."""
    fmt = "%(duration)s|%(filesize_approx)s|%(title)s"
    result = run(
        ["yt-dlp", "--print", fmt, "-f", "bestaudio", url],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        return {"duration": 0, "size": 0, "title": "unknown"}
    parts = result.stdout.strip().split("|")
    duration = int(float(parts[0])) if len(parts) > 0 and parts[0] != "NA" else 0
    size = int(float(parts[1])) if len(parts) > 1 and parts[1] != "NA" else 0
    title = parts[2] if len(parts) > 2 else "unknown"
    return {"duration": duration, "size": size, "title": title}


def try_download_subtitle(url: str, output_prefix: str, lang: str, use_auto: bool) -> bool:
    """Attempt to download subtitles. Returns True on success."""
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

    result = run(cmd, check=False, capture=True)
    if result.returncode != 0:
        return False

    # Check that a .vtt file was actually created
    vtt_files = list(Path(".").glob(f"{output_prefix}*.vtt"))
    return len(vtt_files) > 0


# ---------------------------------------------------------------------------
# Whisper transcription
# ---------------------------------------------------------------------------

def transcribe_with_whisper(
    url: str,
    output_name: str,
    model: str = "base",
    language: str | None = None,
    keep_audio: bool = False,
    download_dir: str | None = None,
    device: str = "gpu",
    quiet: bool = False,
) -> bool:
    """Download audio and transcribe with Whisper. Returns True on success."""
    info_url = get_video_info(url)
    size_mb = info_url["size"] // (1024 * 1024) if info_url["size"] else 0
    duration_min = info_url["duration"] // 60

    suppress = quiet or VERBOSITY == 0
    if not suppress:
        print()
        print(f"  {Colors.BOLD}Video:{Colors.RESET} {info_url['title']}")
        print(f"  {Colors.BOLD}Duration:{Colors.RESET} ~{duration_min} min")
        if size_mb:
            print(f"  {Colors.BOLD}Audio size:{Colors.RESET} ~{size_mb} MB")
        print()

    if not ensure_whisper():
        error("Cannot proceed without Whisper.")
        return False

    # Download audio
    info("Downloading audio...")
    audio_template = f"audio_{output_name}.%(ext)s"
    result = run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "-f", "bestaudio",
         "--output", audio_template, url],
        check=False, quiet=quiet,
    )
    if result.returncode != 0:
        error("Failed to download audio.")
        return False

    audio_file = f"audio_{output_name}.mp3"
    if not Path(audio_file).exists():
        # Try to find the actual audio file
        audio_files = list(Path(".").glob(f"audio_{output_name}.*"))
        if not audio_files:
            error("Audio file not found after download.")
            return False
        audio_file = str(audio_files[0])

    success(f"Audio downloaded: {audio_file}")

    # Transcribe
    device_label = "GPU" if device == "gpu" else "CPU"
    info(f"Transcribing with Whisper (model: {model}, {device_label})... this may take a while.")
    whisper_cmd = ["whisper", audio_file, "--model", model, "--output_format", "vtt"]
    if language:
        whisper_cmd.extend(["--language", language])
    if download_dir:
        whisper_cmd.extend(["--download_root", download_dir])

    # Force CPU by hiding CUDA devices
    env = os.environ.copy()
    if device == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = ""

    whisper_kwargs: dict = {"check": False, "env": env}
    if suppress:
        whisper_kwargs["stdout"] = subprocess.DEVNULL
        whisper_kwargs["stderr"] = subprocess.DEVNULL

    result = subprocess.run(whisper_cmd, **whisper_kwargs)
    if result.returncode != 0 and device == "gpu":
        warn("GPU transcription failed (out of memory?). Falling back to CPU...")
        env["CUDA_VISIBLE_DEVICES"] = ""
        result = subprocess.run(whisper_cmd, **whisper_kwargs)

    if result.returncode != 0:
        error("Whisper transcription failed.")
        return False

    # Rename VTT output
    whisper_vtt = Path(audio_file).with_suffix(".vtt")
    final_vtt = Path(f"{output_name}.vtt")
    if whisper_vtt.exists():
        whisper_vtt.rename(final_vtt)

    success("Transcription complete!")

    # Cleanup audio
    if keep_audio:
        info(f"Audio kept at: {audio_file}")
    else:
        Path(audio_file).unlink(missing_ok=True)
        success("Audio deleted.")

    return True


# ---------------------------------------------------------------------------
# VTT → Plain text conversion
# ---------------------------------------------------------------------------

def _parse_vtt_timestamp(time_str: str) -> str:
    """Parse a VTT timestamp like '00:01:23.000' → '[01:23]' or '[01:01:23]'."""
    parts = time_str.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        return ""
    total = int(h) * 3600 + int(m) * 60 + int(s.split(".")[0])
    if total >= 3600:
        return f"[{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}]"
    return f"[{total // 60:02d}:{total % 60:02d}]"


def _vtt_time_to_seconds(time_str: str) -> int:
    """Convert VTT timestamp '00:01:23.000' to total seconds."""
    parts = time_str.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        return 0
    return int(h) * 3600 + int(m) * 60 + int(s.split(".")[0])


def _seconds_to_ts(total: int) -> str:
    """Convert seconds to 'MM:SS' or 'HH:MM:SS'."""
    if total >= 3600:
        return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
    return f"{total // 60:02d}:{total % 60:02d}"


def _clean_vtt_text(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]*>", "", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return text.strip()


def vtt_to_json(vtt_path: Path, video_info: dict, chunk_size: int = 30) -> str:
    """Convert VTT to JSON with chunked text for RAG ingestion."""
    cues: list[tuple[int, str]] = []
    current_start: int | None = None
    cue_lines: list[str] = []

    with open(vtt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                if current_start is not None and cue_lines:
                    text = _clean_vtt_text(" ".join(cue_lines))
                    if text:
                        cues.append((current_start, text))
                    cue_lines = []
                    current_start = None
                continue
            if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            if "-->" in line:
                current_start = _vtt_time_to_seconds(line.split("-->")[0])
                cue_lines = []
                continue
            if line.isdigit() and current_start is not None:
                continue
            if current_start is not None:
                cue_lines.append(line)

    if current_start is not None and cue_lines:
        text = _clean_vtt_text(" ".join(cue_lines))
        if text:
            cues.append((current_start, text))

    deduped: list[tuple[int, str]] = []
    last_text = ""
    for start, text in cues:
        if text != last_text:
            deduped.append((start, text))
            last_text = text

    chunks = []
    i = 0
    while i < len(deduped):
        chunk_start = deduped[i][0]
        chunk_texts = []
        while i < len(deduped) and deduped[i][0] < chunk_start + chunk_size:
            chunk_texts.append(deduped[i][1])
            i += 1
        if i < len(deduped):
            chunk_end = deduped[i][0]
        else:
            chunk_end = chunk_start + chunk_size
        chunks.append({
            "start": _seconds_to_ts(chunk_start),
            "end": _seconds_to_ts(chunk_end),
            "start_seconds": chunk_start,
            "end_seconds": chunk_end,
            "text": " ".join(chunk_texts),
        })

    result = {
        "title": video_info.get("title", "unknown"),
        "url": video_info.get("url", ""),
        "duration": video_info.get("duration", 0),
        "source": "whisper" if video_info.get("whisper") else "subtitles",
        "chunk_size": chunk_size,
        "chunks": chunks,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def vtt_to_text(vtt_path: Path, output_path: Path, video_info: dict | None = None, timestamps: bool = False) -> None:
    """Convert VTT to plain text, deduplicating overlapping lines."""
    seen: set[str] = set()
    lines: list[str] = []
    current_ts = ""

    with open(vtt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("WEBVTT"):
                continue
            if line.startswith("Kind:"):
                continue
            if line.startswith("Language:"):
                continue
            if "-->" in line:
                if timestamps:
                    current_ts = _parse_vtt_timestamp(line.split("-->")[0])
                continue
            if line.isdigit():
                continue

            # Remove HTML tags
            clean = re.sub(r"<[^>]*>", "", line)
            # Decode HTML entities
            clean = (
                clean.replace("&amp;", "&")
                .replace("&gt;", ">")
                .replace("&lt;", "<")
                .replace("&#39;", "'")
                .replace("&quot;", '"')
            )
            clean = clean.strip()
            if clean and clean not in seen:
                seen.add(clean)
                if timestamps and current_ts:
                    lines.append(f"{current_ts} {clean}")
                else:
                    lines.append(clean)

    with open(output_path, "w", encoding="utf-8") as f:
        if video_info:
            duration = video_info.get("duration", 0)
            duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "unknown"
            header = (
                f"Title: {video_info.get('title', 'unknown')}\n"
                f"URL: {video_info.get('url', 'unknown')}\n"
                f"Duration: {duration_str}\n"
                f"Transcribed: {'Whisper' if video_info.get('whisper') else 'YouTube subtitles'}\n"
                f"\n{'─' * 60}\n\n"
            )
            f.write(header)
        f.write("\n".join(lines))
        f.write("\n")


def vtt_to_stdout(vtt_path: Path, video_info: dict | None = None, timestamps: bool = False) -> None:
    """Convert VTT to plain text and print to stdout."""
    seen: set[str] = set()
    lines: list[str] = []
    current_ts = ""

    with open(vtt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("WEBVTT"):
                continue
            if line.startswith("Kind:"):
                continue
            if line.startswith("Language:"):
                continue
            if "-->" in line:
                if timestamps:
                    current_ts = _parse_vtt_timestamp(line.split("-->")[0])
                continue
            if line.isdigit():
                continue

            clean = re.sub(r"<[^>]*>", "", line)
            clean = (
                clean.replace("&amp;", "&")
                .replace("&gt;", ">")
                .replace("&lt;", "<")
                .replace("&#39;", "'")
                .replace("&quot;", '"')
            )
            clean = clean.strip()
            if clean and clean not in seen:
                seen.add(clean)
                if timestamps and current_ts:
                    lines.append(f"{current_ts} {clean}")
                else:
                    lines.append(clean)

    if video_info:
        duration = video_info.get("duration", 0)
        duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "unknown"
        header = (
            f"Title: {video_info.get('title', 'unknown')}\n"
            f"URL: {video_info.get('url', 'unknown')}\n"
            f"Duration: {duration_str}\n"
            f"Transcribed: {'Whisper' if video_info.get('whisper') else 'YouTube subtitles'}\n"
            f"\n{'─' * 60}\n\n"
        )
        sys.stdout.write(header)
    sys.stdout.write("\n".join(lines))
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------

def _extract_vtt_plain_text(vtt_path: Path) -> str:
    """Extract clean plain text from VTT (for piping to summarizer)."""
    seen: set[str] = set()
    lines: list[str] = []

    with open(vtt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("WEBVTT"):
                continue
            if line.startswith("Kind:") or line.startswith("Language:"):
                continue
            if "-->" in line or line.isdigit():
                continue
            clean = _clean_vtt_text(line)
            if clean and clean not in seen:
                seen.add(clean)
                lines.append(clean)

    return " ".join(lines)


def summarize_text(text: str, cmd: str, prompt: str) -> bool:
    """Pipe text to an external command for summarization."""
    full_input = f"{prompt}\n\n{text}"
    cmd_parts = shlex.split(cmd)
    debug(f"$ echo '...' | {' '.join(cmd_parts)}")

    try:
        result = subprocess.run(
            cmd_parts,
            input=full_input,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        error(f"Summarize command not found: {cmd_parts[0]}")
        return False

    if result.returncode != 0:
        error(f"Summarize command failed: {result.stderr.strip()}")
        return False

    print(result.stdout, end="")
    return True


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def cleanup_temp_files(video_title: str | None = None, keep_audio: bool = False) -> None:
    """Remove leftover temp files from failed or interrupted runs."""
    for f in Path(".").glob("transcript_temp*"):
        f.unlink(missing_ok=True)
    if video_title and not keep_audio:
        for f in Path(".").glob(f"audio_{video_title}.*"):
            f.unlink(missing_ok=True)

def process_video(
    url: str,
    output: str | None = None,
    fmt: str = "txt",
    lang: str = "en",
    list_only: bool = False,
    force_whisper: bool = False,
    whisper_model: str = "base",
    whisper_dir: str | None = None,
    whisper_device: str = "gpu",
    keep_vtt: bool = False,
    keep_audio: bool = False,
    stdout_mode: bool = False,
    timestamps: bool = False,
    chunk_size: int = 30,
    summarize: bool = False,
    summarize_cmd: str | None = None,
    summarize_prompt: str | None = None,
) -> None:
    """Main processing pipeline."""
    ensure_yt_dlp()

    # Redirect info messages to stderr when piping to stdout
    if stdout_mode:
        global info, success, warn
        def _info(msg): print(f"{Colors.BLUE}›{Colors.RESET} {msg}", file=sys.stderr)
        def _success(msg): print(f"{Colors.GREEN}✓{Colors.RESET} {msg}", file=sys.stderr)
        def _warn(msg): print(f"{Colors.YELLOW}⚠{Colors.RESET} {msg}", file=sys.stderr)
        info = _info
        success = _success
        warn = _warn

    if list_only:
        list_subs(url)
        return

    # Auto-detect language if not specified
    if lang is None:
        info("Auto-detecting video language...")
        lang = detect_video_language(url)
        if lang:
            success(f"Detected language: {lang}")
        else:
            lang = "en"
            warn("Could not detect language, falling back to English (en).")

    # Determine output name
    if output:
        video_title = output
    else:
        info("Fetching video title...")
        video_title = get_video_title(url)
        success(f"Video: {video_title}")

    video_duration = get_video_info(url)["duration"]

    # Sanitize output name for use as prefix
    temp_prefix = "transcript_temp"

    try:
        if not force_whisper:
            # List available subs (only in verbose mode)
            if VERBOSITY >= 2 and not stdout_mode:
                info("Available subtitles:")
                run(["yt-dlp", "--list-subs", url], check=False)

            # Strategy: try manual (lang variants → en fallback) → auto (same) → whisper
            lang_variants = get_lang_variants(lang)
            if lang.split("-")[0] != "en":
                lang_variants.extend(get_lang_variants("en"))
            downloaded = False

            for variant in lang_variants:
                info(f"Trying manual subtitles ({variant})...")
                if try_download_subtitle(url, temp_prefix, variant, use_auto=False):
                    downloaded = True
                    success("Manual subtitles downloaded!")
                    break

            if not downloaded:
                for variant in lang_variants:
                    info(f"Trying auto-generated subtitles ({variant})...")
                    if try_download_subtitle(url, temp_prefix, variant, use_auto=True):
                        downloaded = True
                        success("Auto-generated subtitles downloaded!")
                        break

            if downloaded:
                # Find the VTT file
                vtt_files = list(Path(".").glob(f"{temp_prefix}*.vtt"))
                if vtt_files:
                    vtt_file = vtt_files[0]

                    if summarize:
                        if not summarize_cmd:
                            error("--summarize requires summarize_cmd in config or --summarize-cmd flag.")
                            sys.exit(1)
                        info("Extracting text for summarization...")
                        text = _extract_vtt_plain_text(vtt_file)
                        vtt_file.unlink(missing_ok=True)
                        success(f"Piping transcript to: {summarize_cmd}")
                        if not summarize_text(text, summarize_cmd, summarize_prompt or ""):
                            sys.exit(1)
                        return

                    if stdout_mode:
                        if fmt == "vtt":
                            sys.stdout.write(vtt_file.read_text(encoding="utf-8"))
                        elif fmt == "json":
                            sys.stdout.write(vtt_to_json(vtt_file, {
                                "title": video_title,
                                "url": url,
                                "duration": video_duration,
                                "whisper": False,
                            }, chunk_size=chunk_size))
                        else:
                            vtt_to_stdout(vtt_file, {
                                "title": video_title,
                                "url": url,
                                "duration": video_duration,
                                "whisper": False,
                            }, timestamps=timestamps)
                        vtt_file.unlink(missing_ok=True)
                        return

                    final_vtt = Path(f"{video_title}.vtt")
                    vtt_file.rename(final_vtt)

                    if fmt == "vtt":
                        success(f"Saved: {final_vtt}")
                    elif fmt == "json":
                        info("Converting to JSON (chunked for RAG)...")
                        json_output = Path(f"{video_title}.json")
                        json_output.write_text(vtt_to_json(final_vtt, {
                            "title": video_title,
                            "url": url,
                            "duration": video_duration,
                            "whisper": False,
                        }, chunk_size=chunk_size), encoding="utf-8")
                        success(f"Saved: {json_output}")
                        if not keep_vtt:
                            final_vtt.unlink(missing_ok=True)
                    else:
                        # Convert to plain text
                        info("Converting to plain text (deduplicating lines)...")
                        txt_output = Path(f"{video_title}.txt")
                        vtt_to_text(final_vtt, txt_output, {
                            "title": video_title,
                            "url": url,
                            "duration": video_duration,
                            "whisper": False,
                        }, timestamps=timestamps)
                        success(f"Saved: {txt_output}")

                        if keep_vtt:
                            info(f"VTT kept at: {final_vtt}")
                        else:
                            final_vtt.unlink(missing_ok=True)

                    return

            warn("No subtitles available.")
        else:
            warn("Forcing Whisper transcription (--whisper flag).")

        # Last resort: Whisper
        if not transcribe_with_whisper(
            url, video_title, model=whisper_model, language=lang,
            keep_audio=keep_audio, download_dir=whisper_dir,
            device=whisper_device, quiet=stdout_mode or VERBOSITY == 0,
        ):
            error("Could not get transcript. The video may not have subtitles and transcription was not performed.")
            sys.exit(1)

        # Post-process Whisper output
        vtt_file = Path(f"{video_title}.vtt")
        if vtt_file.exists():
            if summarize:
                if not summarize_cmd:
                    error("--summarize requires summarize_cmd in config or --summarize-cmd flag.")
                    sys.exit(1)
                info("Extracting text for summarization...")
                text = _extract_vtt_plain_text(vtt_file)
                vtt_file.unlink(missing_ok=True)
                success(f"Piping transcript to: {summarize_cmd}")
                if not summarize_text(text, summarize_cmd, summarize_prompt or ""):
                    sys.exit(1)
                return

            if stdout_mode:
                if fmt == "vtt":
                    sys.stdout.write(vtt_file.read_text(encoding="utf-8"))
                elif fmt == "json":
                    sys.stdout.write(vtt_to_json(vtt_file, {
                        "title": video_title,
                        "url": url,
                        "duration": video_duration,
                        "whisper": True,
                    }, chunk_size=chunk_size))
                else:
                    vtt_to_stdout(vtt_file, {
                        "title": video_title,
                        "url": url,
                        "duration": video_duration,
                        "whisper": True,
                    }, timestamps=timestamps)
                vtt_file.unlink(missing_ok=True)
            elif fmt == "vtt":
                success(f"Saved: {vtt_file}")
            elif fmt == "json":
                info("Converting to JSON (chunked for RAG)...")
                json_output = Path(f"{video_title}.json")
                json_output.write_text(vtt_to_json(vtt_file, {
                    "title": video_title,
                    "url": url,
                    "duration": video_duration,
                    "whisper": True,
                }, chunk_size=chunk_size), encoding="utf-8")
                success(f"Saved: {json_output}")
                if not keep_vtt:
                    vtt_file.unlink(missing_ok=True)
            else:
                info("Converting to plain text...")
                txt_output = Path(f"{video_title}.txt")
                vtt_to_text(vtt_file, txt_output, {
                    "title": video_title,
                    "url": url,
                    "duration": video_duration,
                    "whisper": True,
                }, timestamps=timestamps)
                success(f"Saved: {txt_output}")

                if not keep_vtt:
                    vtt_file.unlink(missing_ok=True)
    finally:
        cleanup_temp_files(video_title, keep_audio)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yttranscript",
        description="Download YouTube video transcripts (subtitles/captions).",
        epilog=(
            "Examples:\n"
            '  yttranscript "https://youtube.com/watch?v=VIDEO_ID"\n'
            '  yttranscript URL --lang es --format vtt\n'
            "  yttranscript URL --whisper --whisper-model small\n"
            "  yttranscript URL --list-subs\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="YouTube video URL (e.g. https://www.youtube.com/watch?v=...)",
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress all output except errors.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show debug output (commands, yt-dlp/whisper output).",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output filename (without extension). Default: video title.",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["txt", "vtt", "json"],
        default=None,
        help="Output format (default: txt, config: format). json = chunked for RAG.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Seconds per chunk for JSON output (default: 30, config: chunk_size).",
    )
    parser.add_argument(
        "--timestamps",
        action="store_true",
        default=None,
        help="Include [MM:SS] timestamps in text output (config: timestamps).",
    )
    parser.add_argument(
        "--lang",
        default=None,
        help="Subtitle language code (default: auto-detect, config: lang)",
    )
    parser.add_argument(
        "--list-subs",
        action="store_true",
        help="List available subtitles and exit.",
    )
    parser.add_argument(
        "--whisper",
        action="store_true",
        help="Force Whisper transcription (skip subtitle download).",
    )
    parser.add_argument(
        "--whisper-model",
        choices=["tiny", "base", "small", "medium", "large"],
        default=None,
        help="Whisper model size (default: base, config: whisper_model)",
    )
    parser.add_argument(
        "--whisper-dir",
        default=None,
        help="Directory to store Whisper models (default: ~/.cache/whisper/, config: whisper_dir)",
    )
    parser.add_argument(
        "--whisper-device",
        choices=["gpu", "cpu"],
        default=None,
        help="Device for Whisper transcription (default: gpu, config: whisper_device)",
    )
    parser.add_argument(
        "--keep-vtt",
        action="store_true",
        help="Keep the VTT file after converting to text.",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep the audio file after Whisper transcription.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Output transcript to stdout (for piping). No file saved.",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Show current configuration and exit.",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="Pipe transcript to an external AI command for summarization.",
    )
    parser.add_argument(
        "--summarize-cmd",
        default=None,
        help='Command to pipe transcript to (default: config summarize_cmd). Example: "llama-cli -m model.gguf"',
    )
    parser.add_argument(
        "--summarize-prompt",
        default=None,
        help="Prompt prepended to transcript before piping (default: config summarize_prompt).",
    )
    return parser


def show_config() -> None:
    """Display current configuration and exit."""
    config = load_config()
    print(f"\n  {Colors.BOLD}Config file:{Colors.RESET} {CONFIG_PATH}\n")

    keys = ["lang", "format", "timestamps", "chunk_size", "summarize_cmd", "summarize_prompt", "whisper_model", "whisper_device", "whisper_dir"]
    for key in keys:
        raw = config.get(key)
        resolved = resolve_value(None, config, key)
        source = "config" if raw is not None else "default"
        display = resolved if resolved is not None else "auto-detect"
        print(f"  {key + ':':16} {str(display):12} ({source})")

    print()
    sys.exit(0)


def main() -> None:
    global VERBOSITY
    ensure_config_dir()
    parser = build_parser()
    args = parser.parse_args()

    if args.quiet:
        VERBOSITY = 0
    elif args.verbose:
        VERBOSITY = 2

    if args.show_config:
        show_config()

    if not args.url:
        parser.error("a YouTube URL is required")

    config = load_config()

    lang = resolve_value(args.lang, config, "lang")
    fmt = resolve_value(args.format, config, "format")
    timestamps = resolve_value(args.timestamps, config, "timestamps") or False
    chunk_size = resolve_value(args.chunk_size, config, "chunk_size")
    summarize_cmd = resolve_value(args.summarize_cmd, config, "summarize_cmd")
    summarize_prompt = resolve_value(args.summarize_prompt, config, "summarize_prompt")
    whisper_model = resolve_value(args.whisper_model, config, "whisper_model")
    whisper_dir = resolve_value(args.whisper_dir, config, "whisper_dir")
    whisper_device = resolve_value(args.whisper_device, config, "whisper_device")

    try:
        process_video(
            url=args.url,
            output=args.output,
            fmt=fmt,
            lang=lang,
            list_only=args.list_subs,
            force_whisper=args.whisper,
            whisper_model=whisper_model,
            whisper_dir=whisper_dir,
            whisper_device=whisper_device,
            keep_vtt=args.keep_vtt,
            keep_audio=args.keep_audio,
            stdout_mode=args.stdout,
            timestamps=timestamps,
            chunk_size=chunk_size,
            summarize=args.summarize,
            summarize_cmd=summarize_cmd,
            summarize_prompt=summarize_prompt,
        )
    except KeyboardInterrupt:
        print()
        warn("Interrupted by user.")
        sys.exit(130)
    except subprocess.CalledProcessError as e:
        error(f"Command failed: {' '.join(e.cmd) if isinstance(e.cmd, list) else e.cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
