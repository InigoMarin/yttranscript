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
from .util import is_youtube_url, is_valid_lang_code, sanitize_filename, TranscriptError, format_duration
from .ytdlp import list_channel_videos
from .core import process_video
from .pdf import markdown_to_merged, PANDOC_FORMATS
from .web import run_server
from . import db as cache_db


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
        default=None,
        help="Port for web UI (default: 8080, config: port).",
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
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip cache lookup. Force re-download/transcription.",
    )
    parser.add_argument(
        "--skip-cached",
        action="store_true",
        help="Skip processing if the video is already in cache. Prints 'Already in cache' and exits.",
    )
    parser.add_argument(
        "--history",
        nargs="?",
        const=20,
        type=int,
        default=None,
        metavar="N",
        help="List N most recently transcribed videos from cache (default: 20).",
    )
    parser.add_argument(
        "--cache-clear",
        action="store_true",
        help="Delete all cached transcripts and history.",
    )
    parser.add_argument(
        "--cache-remove",
        default=None,
        metavar="URL",
        help="Remove a specific video from cache by URL or video ID.",
    )
    parser.add_argument(
        "--cache-info",
        default=None,
        metavar="URL",
        help="Show cached information for a video.",
    )
    parser.add_argument(
        "--cache-stats",
        action="store_true",
        help="Show cache statistics.",
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


def _resolve_options(args, config: dict) -> dict:
    """Resolve all CLI options from args + config in one pass."""
    cache_enabled = config.get("cache_enabled", DEFAULTS["cache_enabled"])
    use_cache = cache_enabled and not args.no_cache
    return {
        "lang": resolve_value(args.lang, config, "lang"),
        "fmt": resolve_value(args.format, config, "format"),
        "timestamps": resolve_value(args.timestamps, config, "timestamps") or False,
        "chunk_size": resolve_value(args.chunk_size, config, "chunk_size"),
        "summarize_cmd": resolve_value(args.summarize_cmd, config, "summarize_cmd"),
        "summarize_prompt": resolve_value(args.summarize_prompt, config, "summarize_prompt"),
        "summarize_timeout": resolve_value(None, config, "summarize_timeout"),
        "fallback_lang": resolve_value(None, config, "fallback_lang"),
        "whisper_model": resolve_value(args.whisper_model, config, "whisper_model"),
        "whisper_dir": resolve_value(args.whisper_dir, config, "whisper_dir"),
        "whisper_device": resolve_value(args.whisper_device, config, "whisper_device"),
        "use_cache": use_cache,
        "skip_cached": use_cache and args.skip_cached,
    }


def _merge_output_path(args, fmt: str, default_name: str) -> Path:
    """Compute the output path for a merged document."""
    output_dir = Path(args.output_dir) if args.output_dir else Path.cwd()
    merge_ext = f".{fmt}"
    if args.output:
        merge_name = f"{args.output}_merged{merge_ext}"
    else:
        merge_name = f"{sanitize_filename(default_name or 'merged')}{merge_ext}"
    return output_dir / merge_name


def _do_merge(sections: list, args, fmt: str, channel_name: str) -> None:
    """Generate a merged document from collected sections."""
    merge_path = _merge_output_path(args, fmt, channel_name)
    try:
        markdown_to_merged(sections, merge_path, fmt=fmt, channel_name=channel_name)
        info(f"Merged {fmt.upper()}: {merge_path}")
    except Exception as e:
        error(f"Failed to generate merged {fmt.upper()}: {e}")


def transcribe_batch(videos, args, channel_name: str = "", sections_list: list | None = None) -> None:
    """Transcribe a batch of videos listed by --latest --transcribe."""
    config = load_config()
    opts = _resolve_options(args, config)
    lang = opts["lang"]
    fmt = opts["fmt"]
    timestamps = opts["timestamps"]
    chunk_size = opts["chunk_size"]
    summarize_cmd = opts["summarize_cmd"]
    summarize_prompt = opts["summarize_prompt"]
    summarize_timeout = opts["summarize_timeout"]
    fallback_lang = opts["fallback_lang"]
    whisper_model = opts["whisper_model"]
    whisper_dir = opts["whisper_dir"]
    whisper_device = opts["whisper_device"]
    use_cache = opts["use_cache"]
    skip_cached = opts["skip_cached"]

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
    if sections_list is not None:
        collected_sections = sections_list
    else:
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
                use_cache=use_cache,
                skip_cached=skip_cached,
            )
            succeeded += 1
            if args.merge and result and result[1]:
                vi = result[2] if len(result) > 2 else {}
                collected_sections.append((
                    {"title": title, "url": video_url, "duration": vi.get("duration", 0),
                     "channel": vi.get("channel", channel_name), "upload_date": vi.get("upload_date", _date_str)},
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

    if args.merge and collected_sections and sections_list is None:
        _do_merge(collected_sections, args, fmt, channel_name)

    info(f"Done: {succeeded} transcribed, {failed} failed.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.quiet:
        log.set_verbosity(0)
    elif args.verbose:
        log.set_verbosity(2)

    # Resolve port from config early so _validate_args can range-check it.
    _config = load_config()
    args.port = resolve_value(args.port, _config, "port")

    _validate_args(parser, args)

    # Create config dir only when we'll actually use it (not for --version / --help).
    if not args.show_config:
        ensure_config_dir()

    if args.show_config:
        show_config()

    # --- Cache management commands (no URL needed) ---
    if args.cache_clear:
        count = cache_db.clear_all()
        info(f"Cleared {count} videos from cache.")
        sys.exit(0)

    if args.cache_remove:
        vid = cache_db.extract_video_id(args.cache_remove) or args.cache_remove
        if cache_db.remove_video(vid):
            info(f"Removed {vid} from cache.")
        else:
            warn(f"{vid} not found in cache.")
        sys.exit(0)

    if args.cache_stats:
        stats = cache_db.get_stats()
        print(f"\n  {Colors.BOLD}Cache Statistics{Colors.RESET}\n")
        print(f"  Total videos:      {stats['total_videos']}")
        print(f"  Total transcripts: {stats['total_transcripts']}")
        if stats["by_format"]:
            formats = ", ".join(f"{k}={v}" for k, v in sorted(stats["by_format"].items()))
            print(f"  By format:         {formats}")
        if stats["by_channel"]:
            channels = ", ".join(f"{k}={v}" for k, v in stats["by_channel"].items())
            print(f"  Top channels:      {channels}")
        size_mb = stats["db_size_bytes"] / (1024 * 1024)
        print(f"  Database size:     {size_mb:.1f} MB\n")
        sys.exit(0)

    if args.history is not None:
        entries = cache_db.list_history(limit=args.history)
        if not entries:
            warn("Cache is empty.")
        else:
            print(f"\n  {Colors.BOLD}Recent Transcriptions{Colors.RESET}\n")
            for e in entries:
                date = (e.get("last_accessed") or "")[:10]
                title = (e.get("title") or "?")[:60]
                channel = e.get("channel") or "?"
                dur = format_duration(e.get("duration") or 0)
                lang = e.get("language") or "?"
                fmts = e.get("formats") or ""
                url = e.get("url") or ""
                print(f"  {date}  {title}")
                print(f"    {channel} · {dur} · {lang} · formats: {fmts}")
                print(f"    {url}")
                print()
        sys.exit(0)

    if args.cache_info:
        vid = cache_db.extract_video_id(args.cache_info) or args.cache_info
        entry = cache_db.get_video_info(vid)
        if not entry:
            warn(f"{vid} not found in cache.")
            sys.exit(0)
        print(f"\n  {Colors.BOLD}Cache Info: {vid}{Colors.RESET}\n")
        print(f"  Title:       {entry.get('title', '?')}")
        print(f"  URL:         {entry.get('url', '?')}")
        print(f"  Channel:     {entry.get('channel', '?')}")
        print(f"  Duration:    {format_duration(entry.get('duration') or 0)}")
        print(f"  Upload date: {entry.get('upload_date', '?')}")
        print(f"  First seen:  {entry.get('first_seen', '?')}")
        print(f"  Last access: {entry.get('last_accessed', '?')}")
        if entry.get("cached_formats"):
            fmts = ", ".join(
                f"{f['format']}/{f['language']}" for f in entry["cached_formats"]
            )
            print(f"  Cached as:   {fmts}")
        print()
        sys.exit(0)

    if args.serve:
        run_server(args.port)
        return

    if not args.url and not args.group:
        parser.error("a YouTube URL is required (or use --serve, --group, --history, or --cache-*)")

    if args.url and not is_youtube_url(args.url):
        parser.error(f"not a YouTube URL: {args.url!r}")

    if args.group is not None:
        config = load_config()
        urls = resolve_channel_group(config, args.group)
        all_sections: list[tuple[dict, str]] = []
        for url in urls:
            if not is_youtube_url(url):
                warn(f"Skipping non-YouTube URL in group {args.group!r}: {url}")
                continue
            channel_name, videos = list_channel_videos(url, args.latest or 10)
            if not videos:
                warn(f"No videos found for {url}")
                continue
            info(f"Group {args.group!r}: transcribing {len(videos)} videos from {channel_name}")
            batch_sections: list[tuple[dict, str]] = []
            transcribe_batch(videos, args, channel_name=channel_name, sections_list=batch_sections)
            all_sections.extend(batch_sections)
        if args.merge and all_sections:
            fmt = resolve_value(args.format, config, "format")
            _do_merge(all_sections, args, fmt, args.group)
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
    opts = _resolve_options(args, config)

    try:
        process_video(
            url=args.url,
            output=args.output,
            fmt=opts["fmt"],
            lang=opts["lang"],
            list_only=args.list_subs,
            force_whisper=args.whisper,
            whisper_model=opts["whisper_model"],
            whisper_dir=opts["whisper_dir"],
            whisper_device=opts["whisper_device"],
            keep_vtt=args.keep_vtt,
            keep_audio=args.keep_audio,
            stdout_mode=args.stdout,
            timestamps=opts["timestamps"],
            chunk_size=opts["chunk_size"],
            summarize=args.summarize,
            summarize_cmd=opts["summarize_cmd"],
            summarize_prompt=opts["summarize_prompt"],
            summarize_timeout=opts["summarize_timeout"],
            fallback_lang=opts["fallback_lang"],
            work_dir=args.work_dir,
            output_dir=args.output_dir,
            use_cache=opts["use_cache"],
            skip_cached=opts["skip_cached"],
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
