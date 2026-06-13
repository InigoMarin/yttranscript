"""Whisper transcription fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from . import log
from .log import info, success, warn, error, Colors
from .util import run
from .ytdlp import get_video_info, ensure_whisper, TIMEOUT_AUDIO_DOWNLOAD

# Whisper transcription can be very slow (hours for `large` on CPU). Use a
# generous safety net; user can always Ctrl-C.
WHISPER_TIMEOUT = 4 * 3600  # 4 hours


def transcribe_with_whisper(
    url: str,
    output_name: str,
    model: str = "base",
    language: Optional[str] = None,
    keep_audio: bool = False,
    download_dir: Optional[str] = None,
    device: str = "gpu",
    quiet: bool = False,
    video_info: Optional[dict] = None,
    work_dir: Optional[Path] = None,
    keep_audio_dir: Optional[Path] = None,
    timeout: float = WHISPER_TIMEOUT,
) -> bool:
    """Download audio and transcribe with Whisper. Returns True on success.

    Intermediate files (audio, whisper VTT) are written to `work_dir` when
    given, otherwise to CWD. When `keep_audio` is True and `keep_audio_dir` is
    given, the audio file is moved there (typically the user's CWD).
    """
    if not shutil.which("ffmpeg"):
        error(
            "ffmpeg is required for Whisper transcription but was not found.\n"
            "Install it with one of:\n"
            "  Ubuntu/Debian:  sudo apt install ffmpeg\n"
            "  macOS:          brew install ffmpeg\n"
            "  Arch Linux:     sudo pacman -S ffmpeg\n"
            "  Windows:        winget install ffmpeg\n"
            "  Any system:     pip install imageio-ffmpeg"
        )
        return False
    info_url = video_info if video_info is not None else get_video_info(url)
    size_mb = info_url["size"] // (1024 * 1024) if info_url["size"] else 0
    duration_min = info_url["duration"] // 60

    suppress = quiet or log.VERBOSITY == 0
    if not suppress:
        info(f"{Colors.BOLD}Video:{Colors.RESET} {info_url['title']}")
        info(f"{Colors.BOLD}Duration:{Colors.RESET} ~{duration_min} min")
        if size_mb:
            info(f"{Colors.BOLD}Audio size:{Colors.RESET} ~{size_mb} MB")

    if not ensure_whisper():
        error("Whisper is required but could not be installed. Try: pip install openai-whisper")
        return False

    work_path = work_dir if work_dir is not None else Path(".")

    # Download audio into work_path (absolute template so yt-dlp writes there
    # regardless of the process CWD).
    info("Downloading audio...")
    audio_template = str(work_path / f"audio_{output_name}.%(ext)s")
    result = run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "-f", "bestaudio",
         "--output", audio_template, url],
        check=False, quiet=quiet, timeout=TIMEOUT_AUDIO_DOWNLOAD,
    )
    if result.returncode != 0:
        error("Failed to download audio. The video may be restricted, private, or region-locked.")
        return False

    audio_file = work_path / f"audio_{output_name}.mp3"
    if not audio_file.exists():
        # Try to find the actual audio file in work_path
        audio_files = list(work_path.glob(f"audio_{output_name}.*"))
        if not audio_files:
            error("Audio file not found after download.")
            return False
        audio_file = audio_files[0]

    success(f"Audio downloaded: {audio_file}")

    # Transcribe. Use --output_dir so Whisper writes the VTT into work_path
    # regardless of CWD (also makes it thread-safe under the web server).
    # Detect GPU availability to avoid a wasted failed attempt on CPU-only hosts.
    if device == "gpu" and not shutil.which("nvidia-smi"):
        warn("No NVIDIA GPU detected (nvidia-smi not found). Using CPU.")
        device = "cpu"
    device_label = "GPU" if device == "gpu" else "CPU"
    info(f"Transcribing with Whisper (model: {model}, {device_label})... this may take a while.")
    whisper_cmd = [
        "whisper", str(audio_file),
        "--model", model,
        "--output_format", "vtt",
        "--output_dir", str(work_path),
    ]
    if language:
        whisper_cmd.extend(["--language", language])
    if download_dir:
        whisper_cmd.extend(["--download_root", download_dir])

    # Force CPU by hiding CUDA devices
    env = os.environ.copy()
    if device == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = ""

    whisper_kwargs: dict = {"check": False, "env": env, "timeout": timeout}
    if suppress:
        whisper_kwargs["stdout"] = subprocess.DEVNULL
        whisper_kwargs["stderr"] = subprocess.DEVNULL

    result = subprocess.run(whisper_cmd, **whisper_kwargs)
    if result.returncode != 0 and device == "gpu":
        warn("GPU transcription failed (out of memory?). Falling back to CPU...")
        env["CUDA_VISIBLE_DEVICES"] = ""
        result = subprocess.run(whisper_cmd, **whisper_kwargs)

    if result.returncode != 0:
        error(
            "Whisper transcription failed. Possible causes:\n"
            "  - Out of memory (try a smaller --whisper-model, e.g. 'tiny' or 'base')\n"
            "  - ffmpeg not installed or not on PATH\n"
            "  - Corrupted audio file\n"
            "Run with --verbose for detailed error output."
        )
        return False

    # Rename VTT output (inside work_path) to the final name.
    whisper_vtt = audio_file.with_suffix(".vtt")
    final_vtt = work_path / f"{output_name}.vtt"
    if whisper_vtt.exists():
        whisper_vtt.rename(final_vtt)

    success("Transcription complete!")

    # Cleanup / preserve audio
    if keep_audio:
        if keep_audio_dir is not None and keep_audio_dir.resolve() != work_path.resolve():
            target = keep_audio_dir / audio_file.name
            shutil.move(str(audio_file), str(target))
            info(f"Audio kept at: {target}")
        else:
            info(f"Audio kept at: {audio_file}")
    else:
        audio_file.unlink(missing_ok=True)
        success("Audio deleted.")

    return True
