"""Command-line interface: argument parsing and entry point."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import log
from ._version import __version__
from .log import info, warn, error, Colors
from .config import (
    CONFIG_PATH, DEFAULTS, load_config, resolve_value, ensure_config_dir, hidden_keys,
    resolve_channel_group,
)
from .util import is_youtube_url, is_valid_lang_code, sanitize_filename, TranscriptError
from .ytdlp import list_channel_videos
from .core import process_video
from .pdf import markdown_to_merged, PANDOC_FORMATS
from .web import run_server


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
            "  yttranscript URL --latest 5\n"
            "  yttranscript URL --latest 5 --transcribe\n"
            "  yttranscript --group tech --transcribe\n"
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
        choices=["txt", "vtt", "srt", "json", "pdf", "epub", "docx"],
        default=None,
        help="Output format (default: txt, config: format). json = chunked for RAG. pdf/epub/docx = via Pandoc.",
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
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start local web UI (http://localhost:PORT).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for web UI (default: 8080).",
    )
    parser.add_argument(
        "--latest",
        nargs="?",
        const=10,
        type=int,
        default=None,
        metavar="N",
        help="List latest N videos from a channel (default: 10). Accepts channel or video URLs.",
    )
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="With --latest, transcribe all listed videos (batch mode). "
             "All other options (--lang, --format, --summarize, ...) apply to each video.",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="With --latest --transcribe --format pdf/epub/docx --summarize, also generate "
             "a single merged document with all summaries. Without --output, named after the channel.",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Directory for intermediate files (subtitle/audio/VTT). Default: private tempdir.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where the final transcript is saved. Default: current directory.",
    )
    parser.add_argument(
        "--group",
        default=None,
        metavar="NAME",
        help="Transcribe all channels in a named group from config (requires --transcribe).",
    )
    return parser


def show_config() -> None:
    """Display current configuration and exit."""
    config = load_config()
    print(f"\n  {Colors.BOLD}Config file:{Colors.RESET} {CONFIG_PATH}\n")

    for key in DEFAULTS:
        if key in hidden_keys():
            continue
        raw = config.get(key)
        resolved = resolve_value(None, config, key)
        source = "config" if raw is not None else "default"
        display = resolved if resolved is not None else "auto-detect"
        print(f"  {key + ':':20} {str(display):12} ({source})")

    channels = config.get("channels", {})
    if channels:
        print(f"\n  {Colors.BOLD}Channel groups:{Colors.RESET}\n")
        for group_name, group_urls in channels.items():
            print(f"  {group_name}:")
            for url in group_urls:
                print(f"    - {url}")

    print()
    sys.exit(0)


def _validate_args(parser: argparse.ArgumentParser, args) -> None:
    """Validate interdependent / range-checked arguments."""
    if not (1 <= args.port <= 65535):
        parser.error(f"--port must be 1-65535, got {args.port}")
    if args.chunk_size is not None and args.chunk_size < 1:
        parser.error(f"--chunk-size must be >= 1, got {args.chunk_size}")
    if args.latest is not None and args.latest < 1:
        parser.error(f"--latest must be >= 1, got {args.latest}")
    if args.lang is not None and not is_valid_lang_code(args.lang):
        parser.error(
            f"{args.lang!r} is not a valid language code.\n"
            "Expected a 2-letter code (e.g. 'es', 'en', 'fr') "
            "or with region (e.g. 'pt-BR', 'zh-Hans')."
        )
    if args.merge and not args.transcribe:
        parser.error("--merge requires --transcribe")
    if args.group is not None and not args.transcribe:
        parser.error("--group requires --transcribe")


def transcribe_batch(videos, args, channel_name: str = "") -> None:
    """Transcribe a batch of videos listed by --latest --transcribe."""
    config = load_config()
    lang = resolve_value(args.lang, config, "lang")
    fmt = resolve_value(args.format, config, "format")
    timestamps = resolve_value(args.timestamps, config, "timestamps") or False
    chunk_size = resolve_value(args.chunk_size, config, "chunk_size")
    summarize_cmd = resolve_value(args.summarize_cmd, config, "summarize_cmd")
    summarize_prompt = resolve_value(args.summarize_prompt, config, "summarize_prompt")
    summarize_timeout = resolve_value(None, config, "summarize_timeout")
    fallback_lang = resolve_value(None, config, "fallback_lang")
    whisper_model = resolve_value(args.whisper_model, config, "whisper_model")
    whisper_dir = resolve_value(args.whisper_dir, config, "whisper_dir")
    whisper_device = resolve_value(args.whisper_device, config, "whisper_device")

    if args.merge and fmt not in PANDOC_FORMATS:
        from .log import error as _error
        _error(
            f"--merge requires --format to be one of {', '.join(sorted(PANDOC_FORMATS))}, "
            f"got '{fmt}'"
        )
        sys.exit(2)

    total = len(videos)
    succeeded = 0
    failed = 0
    collected_sections: list[tuple[dict, str]] = []

    for i, (_date_str, video_id, title) in enumerate(videos, 1):
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        info(f"[{i}/{total}] Transcribing: {title!r}")
        try:
            result = process_video(
                url=video_url,
                output=f"{args.output}_{sanitize_filename(title)}" if args.output else None,
                fmt=fmt,
                lang=lang,
                list_only=False,
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
                summarize_timeout=summarize_timeout,
                fallback_lang=fallback_lang,
                work_dir=args.work_dir,
                output_dir=args.output_dir,
            )
            succeeded += 1
            if args.merge and result and result[1]:
                collected_sections.append((
                    {"title": title, "url": video_url, "duration": 0},
                    result[1],
                ))
        except KeyboardInterrupt:
            warn("Batch interrupted by user.")
            break
        except TranscriptError as e:
            error(f"Failed: {e}")
            failed += 1
        except Exception as e:
            msg = str(e) if str(e) else type(e).__name__
            error(f"Failed: {msg}")
            failed += 1

    if args.merge and collected_sections:
        output_dir = Path(args.output_dir) if args.output_dir else Path.cwd()
        merge_ext = f".{fmt}"
        if args.output:
            merge_name = f"{args.output}_merged{merge_ext}"
        else:
            merge_name = f"{sanitize_filename(channel_name or 'merged')}{merge_ext}"
        merge_path = output_dir / merge_name
        try:
            markdown_to_merged(collected_sections, merge_path, fmt=fmt, channel_name=channel_name)
            info(f"Merged {fmt.upper()}: {merge_path}")
        except Exception as e:
            error(f"Failed to generate merged {fmt.upper()}: {e}")

    info(f"Done: {succeeded} transcribed, {failed} failed.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.quiet:
        log.set_verbosity(0)
    elif args.verbose:
        log.set_verbosity(2)

    _validate_args(parser, args)

    # Create config dir only when we'll actually use it (not for --version / --help).
    if not args.show_config:
        ensure_config_dir()

    if args.show_config:
        show_config()

    if args.serve:
        run_server(args.port)
        return

    if not args.url and not args.group:
        parser.error("a YouTube URL is required (or use --serve or --group)")

    if args.url and not is_youtube_url(args.url):
        parser.error(f"not a YouTube URL: {args.url!r}")

    if args.group is not None:
        config = load_config()
        urls = resolve_channel_group(config, args.group)
        for url in urls:
            if not is_youtube_url(url):
                warn(f"Skipping non-YouTube URL in group {args.group!r}: {url}")
                continue
            channel_name, videos = list_channel_videos(url, args.latest or 10)
            if not videos:
                warn(f"No videos found for {url}")
                continue
            info(f"Group {args.group!r}: transcribing {len(videos)} videos from {channel_name}")
            transcribe_batch(videos, args, channel_name=channel_name)
        return

    if args.latest is not None:
        channel_name, videos = list_channel_videos(args.url, args.latest)
        if not args.transcribe:
            return
        if args.list_subs:
            parser.error("--list-subs cannot be used with --latest --transcribe")
        transcribe_batch(videos, args, channel_name=channel_name)
        return

    config = load_config()

    lang = resolve_value(args.lang, config, "lang")
    fmt = resolve_value(args.format, config, "format")
    timestamps = resolve_value(args.timestamps, config, "timestamps") or False
    chunk_size = resolve_value(args.chunk_size, config, "chunk_size")
    summarize_cmd = resolve_value(args.summarize_cmd, config, "summarize_cmd")
    summarize_prompt = resolve_value(args.summarize_prompt, config, "summarize_prompt")
    summarize_timeout = resolve_value(None, config, "summarize_timeout")
    fallback_lang = resolve_value(None, config, "fallback_lang")
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
            summarize_timeout=summarize_timeout,
            fallback_lang=fallback_lang,
            work_dir=args.work_dir,
            output_dir=args.output_dir,
        )
    except KeyboardInterrupt:
        print()
        warn("Interrupted by user.")
        sys.exit(130)
    except subprocess.TimeoutExpired as e:
        error("Operation timed out. This can happen with slow internet or very long videos.")
        if log.VERBOSITY >= 2:
            cmd_str = " ".join(e.cmd) if isinstance(e.cmd, list) else str(e.cmd)
            log.debug(f"Timed out after {e.timeout}s: {cmd_str}")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        error("A required tool failed. Run with --verbose for details.")
        if log.VERBOSITY >= 2:
            cmd_str = " ".join(e.cmd) if isinstance(e.cmd, list) else str(e.cmd)
            log.debug(f"Command failed (exit {e.returncode}): {cmd_str}")
        sys.exit(1)
    except TranscriptError as e:
        error(str(e))
        sys.exit(1)
    except Exception as e:
        msg = str(e) if str(e) else "An unexpected error occurred."
        error(msg)
        if log.VERBOSITY >= 2:
            log.debug(f"{type(e).__name__}: {e}")
        else:
            warn("Run with --verbose for technical details.")
        sys.exit(1)
