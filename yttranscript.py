#!/usr/bin/env python3
"""YouTube Transcript Downloader CLI.

Download transcripts (subtitles/captions) from YouTube videos.
Falls back to Whisper transcription when no subtitles are available.
"""

__version__ = "1.5.0"

import argparse
import os
import re
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
    "whisper_model": "base",
    "whisper_device": "gpu",
    "whisper_dir": None,
    "output": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def info(msg: str) -> None:
    print(f"{Colors.BLUE}›{Colors.RESET} {msg}")


def success(msg: str) -> None:
    print(f"{Colors.GREEN}✓{Colors.RESET} {msg}")


def warn(msg: str) -> None:
    print(f"{Colors.YELLOW}⚠{Colors.RESET} {msg}")


def error(msg: str) -> None:
    print(f"{Colors.RED}✗{Colors.RESET} {msg}", file=sys.stderr)


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command and optionally capture output."""
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=check)
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


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True on success."""
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if command_exists(cmd[0]):
            try:
                proc = subprocess.run(cmd, input=text, text=True, check=True)
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                return False
    warn("No clipboard tool found. Install one of: wl-copy, xclip, xsel")
    return False


def load_config() -> dict:
    """Load config from ~/.config/yttranscript/config.toml."""
    if tomllib is None or not CONFIG_PATH.exists():
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
    return lang


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
) -> bool:
    """Download audio and transcribe with Whisper. Returns True on success."""
    info_url = get_video_info(url)
    size_mb = info_url["size"] // (1024 * 1024) if info_url["size"] else 0
    duration_min = info_url["duration"] // 60

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
        check=False,
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

    result = subprocess.run(whisper_cmd, check=False, env=env)
    if result.returncode != 0 and device == "gpu":
        warn("GPU transcription failed (out of memory?). Falling back to CPU...")
        env["CUDA_VISIBLE_DEVICES"] = ""
        result = subprocess.run(whisper_cmd, check=False, env=env)

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

def vtt_to_text(vtt_path: Path, output_path: Path, video_info: dict | None = None) -> None:
    """Convert VTT to plain text, deduplicating overlapping lines."""
    seen: set[str] = set()
    lines: list[str] = []

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


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

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
    clipboard: bool = False,
) -> None:
    """Main processing pipeline."""
    ensure_yt_dlp()

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

    if not force_whisper:
        # List available subs (informational)
        info("Checking available subtitles...")
        run(["yt-dlp", "--list-subs", url], check=False)

        # Strategy: try manual → auto → whisper
        downloaded = False
        sub_type = None

        info("Trying manual subtitles...")
        if try_download_subtitle(url, temp_prefix, lang, use_auto=False):
            downloaded = True
            sub_type = "manual"
            success("Manual subtitles downloaded!")
        else:
            info("Manual subtitles not available. Trying auto-generated...")
            if try_download_subtitle(url, temp_prefix, lang, use_auto=True):
                downloaded = True
                sub_type = "auto"
                success("Auto-generated subtitles downloaded!")

        if downloaded:
            # Find the VTT file
            vtt_files = list(Path(".").glob(f"{temp_prefix}*.vtt"))
            if vtt_files:
                vtt_file = vtt_files[0]
                final_vtt = Path(f"{video_title}.vtt")
                vtt_file.rename(final_vtt)

                if fmt == "vtt":
                    success(f"Saved: {final_vtt}")
                else:
                    # Convert to plain text
                    info("Converting to plain text (deduplicating lines)...")
                    txt_output = Path(f"{video_title}.txt")
                    vtt_to_text(final_vtt, txt_output, {
                        "title": video_title,
                        "url": url,
                        "duration": video_duration,
                        "whisper": False,
                    })
                    success(f"Saved: {txt_output}")

                    if clipboard:
                        copy_to_clipboard(txt_output.read_text(encoding="utf-8"))
                        success("Copied to clipboard.")

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
        device=whisper_device,
    ):
        error("Could not get transcript. The video may not have subtitles and transcription was not performed.")
        sys.exit(1)

    # Post-process Whisper output
    vtt_file = Path(f"{video_title}.vtt")
    if vtt_file.exists():
        if fmt == "vtt":
            success(f"Saved: {vtt_file}")
        else:
            info("Converting to plain text...")
            txt_output = Path(f"{video_title}.txt")
            vtt_to_text(vtt_file, txt_output, {
                "title": video_title,
                "url": url,
                "duration": video_duration,
                "whisper": True,
            })
            success(f"Saved: {txt_output}")

            if clipboard:
                copy_to_clipboard(txt_output.read_text(encoding="utf-8"))
                success("Copied to clipboard.")

            if not keep_vtt:
                vtt_file.unlink(missing_ok=True)


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
        "-o", "--output",
        help="Output filename (without extension). Default: video title.",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["txt", "vtt"],
        default=None,
        help="Output format (default: txt, config: format)",
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
        "-c", "--clipboard",
        action="store_true",
        help="Copy transcript to system clipboard.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.url:
        parser.error("a YouTube URL is required")

    config = load_config()

    lang = resolve_value(args.lang, config, "lang")
    fmt = resolve_value(args.format, config, "format")
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
            clipboard=args.clipboard,
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
