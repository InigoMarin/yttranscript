"""Main transcript processing pipeline."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from . import log
from .log import info, success, warn, log_context
from .util import run, is_youtube_url, is_playlist_url, sanitize_filename, TranscriptError
from .vtt import (
    vtt_to_json,
    vtt_to_text,
    vtt_to_stdout,
    vtt_to_srt,
    format_video_header,
    extract_vtt_plain_text,
    _vtt_to_plain,
)
from .whisper import transcribe_with_whisper
from .summarize import summarize_text
from .pdf import markdown_to_pdf, markdown_to_epub, markdown_to_docx
from .ytdlp import (
    ensure_yt_dlp,
    get_video_metadata,
    list_subs,
    try_download_subtitle,
    get_lang_variants,
)


def _render_output(
    vtt_path: Path,
    video_info: dict,
    fmt: str,
    stdout_mode: bool,
    timestamps: bool,
    chunk_size: int,
    summarize: bool,
    summarize_cmd: Optional[str],
    summarize_prompt: Optional[str],
    summarize_timeout: int,
    keep_vtt: bool,
    output_dir: Path,
) -> Optional[tuple[Path, Optional[str]]]:
    """Render VTT to final output: summarize, stdout, or file in output_dir.

    Returns a tuple of (output_file_or_None, summary_markdown_or_None).
    summary_markdown is populated only when summarize=True and a file is saved.
    """
    if summarize:
        if not summarize_cmd:
            raise TranscriptError("--summarize requires summarize_cmd in config or --summarize-cmd flag.")
        info("Extracting text for summarization...")
        text = extract_vtt_plain_text(vtt_path)
        vtt_path.unlink(missing_ok=True)
        success(f"Piping transcript to: {summarize_cmd}")
        summary = summarize_text(text, summarize_cmd, summarize_prompt or "", summarize_timeout)
        if not summary:
            raise TranscriptError("Summarization failed.")
        if stdout_mode:
            print(format_video_header(video_info), end="")
            print(summary)
            return (None, None)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            full_text = format_video_header(video_info) + summary + "\n"
            safe_title = sanitize_filename(video_info.get('title', 'transcript'))
            if fmt == "pdf":
                out = output_dir / f"{safe_title}.pdf"
                markdown_to_pdf(summary, out, video_info=video_info)
            elif fmt == "epub":
                out = output_dir / f"{safe_title}.epub"
                markdown_to_epub(summary, out, video_info=video_info)
            elif fmt == "docx":
                out = output_dir / f"{safe_title}.docx"
                markdown_to_docx(summary, out, video_info=video_info)
            else:
                out = output_dir / f"{safe_title}.txt"
                out.write_text(full_text, encoding="utf-8")
            success(f"Saved: {out}")
        return (out, summary)

    if stdout_mode:
        if fmt == "vtt":
            sys.stdout.write(vtt_path.read_text(encoding="utf-8"))
        elif fmt == "srt":
            sys.stdout.write(vtt_to_srt(vtt_path))
        elif fmt == "json":
            sys.stdout.write(vtt_to_json(vtt_path, video_info, chunk_size=chunk_size))
        else:
            vtt_to_stdout(vtt_path, video_info, timestamps=timestamps)
        vtt_path.unlink(missing_ok=True)
        return (None, None)

    output_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "vtt":
        target = output_dir / vtt_path.name
        if target.resolve() != vtt_path.resolve():
            shutil.move(str(vtt_path), str(target))
        else:
            target = vtt_path
        success(f"Saved: {target}")
        return (target, None)

    if fmt == "json":
        info("Converting to JSON (chunked for RAG)...")
        out = output_dir / f"{vtt_path.stem}.json"
        out.write_text(vtt_to_json(vtt_path, video_info, chunk_size=chunk_size), encoding="utf-8")
        success(f"Saved: {out}")
    elif fmt == "srt":
        info("Converting to SRT subtitles...")
        out = output_dir / f"{vtt_path.stem}.srt"
        out.write_text(vtt_to_srt(vtt_path), encoding="utf-8")
        success(f"Saved: {out}")
    elif fmt == "pdf":
        md_text = _vtt_to_plain(vtt_path, video_info=None, timestamps=timestamps)
        out = output_dir / f"{vtt_path.stem}.pdf"
        markdown_to_pdf(md_text, out, video_info=video_info)
        success(f"Saved: {out}")
    elif fmt == "epub":
        md_text = _vtt_to_plain(vtt_path, video_info=None, timestamps=timestamps)
        out = output_dir / f"{vtt_path.stem}.epub"
        markdown_to_epub(md_text, out, video_info=video_info)
        success(f"Saved: {out}")
    elif fmt == "docx":
        md_text = _vtt_to_plain(vtt_path, video_info=None, timestamps=timestamps)
        out = output_dir / f"{vtt_path.stem}.docx"
        markdown_to_docx(md_text, out, video_info=video_info)
        success(f"Saved: {out}")
    else:  # txt
        info("Converting to plain text (deduplicating lines)...")
        out = output_dir / f"{vtt_path.stem}.txt"
        vtt_to_text(vtt_path, out, video_info, timestamps=timestamps)
        success(f"Saved: {out}")

    if keep_vtt:
        vtt_target = output_dir / vtt_path.name
        if vtt_target.resolve() != vtt_path.resolve():
            shutil.move(str(vtt_path), str(vtt_target))
            info(f"VTT kept at: {vtt_target}")
        else:
            info(f"VTT kept at: {vtt_path}")
    else:
        vtt_path.unlink(missing_ok=True)

    return (out, None)


def process_video(
    url: str,
    output: Optional[str] = None,
    fmt: str = "txt",
    lang: Optional[str] = None,
    list_only: bool = False,
    force_whisper: bool = False,
    whisper_model: str = "base",
    whisper_dir: Optional[str] = None,
    whisper_device: str = "gpu",
    keep_vtt: bool = False,
    keep_audio: bool = False,
    stdout_mode: bool = False,
    timestamps: bool = False,
    chunk_size: int = 30,
    summarize: bool = False,
    summarize_cmd: Optional[str] = None,
    summarize_prompt: Optional[str] = None,
    summarize_timeout: int = 300,
    fallback_lang: str = "en",
    log_callback: Optional[Callable[[str, str], None]] = None,
    work_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Optional[tuple[str, Optional[str], dict]]:
    """Main processing pipeline. Returns (video_title, summary_markdown, video_info) or None.

    `work_dir`: directory for intermediate files (subtitle/audio/VTT). Defaults
        to a private TemporaryDirectory, so the user's CWD is no longer polluted
        with `transcript_temp*` / `audio_*` artifacts.
    `output_dir`: where the final rendered file is placed. Defaults to CWD.
    """
    if not is_youtube_url(url):
        raise TranscriptError(f"Not a YouTube URL: {url!r}")

    if is_playlist_url(url) and "/playlist" not in url:
        warn("URL contains a playlist parameter — yt-dlp may process all videos in the playlist.")

    ensure_yt_dlp()

    # Set up work dir for intermediate files. When the caller doesn't supply
    # one, create a private tempdir and clean it up on exit.
    if work_dir is None:
        work_ctx = tempfile.TemporaryDirectory(prefix="yttranscript_")
        work_path = Path(work_ctx.name)
    else:
        work_ctx = None
        work_path = Path(work_dir)
        work_path.mkdir(parents=True, exist_ok=True)

    final_output_dir = Path(output_dir) if output_dir is not None else Path.cwd()

    video_title: Optional[str] = None
    try:
        # Set up per-call log routing (thread-safe; replaces former global
        # reassignment that raced across concurrent web server threads).
        with log_context(log_callback, stdout_mode=stdout_mode):
            if list_only:
                list_subs(url)
                return None

            # Single yt-dlp call for all metadata (language, title, duration, size)
            info("Fetching video metadata...")
            metadata = get_video_metadata(url)

            # Auto-detect language if not specified
            if lang is None:
                lang = metadata.get("language")
                if lang:
                    success(f"Detected language: {lang}")
                else:
                    lang = fallback_lang
                    warn(f"Could not detect language, falling back to {fallback_lang}.")

            # Determine output name
            if output:
                video_title = output
            else:
                video_title = metadata["sanitized_title"]
                success(f"Video: {video_title}")

            # Build video_info from single metadata call; reused by Whisper below.
            video_info = {
                "duration": metadata["duration"],
                "size": metadata["size"],
                "title": metadata["title"],
                "channel": metadata.get("channel", ""),
                "upload_date": metadata.get("upload_date", ""),
            }
            video_duration = video_info["duration"]

            # Intermediate files go into work_path (absolute paths so subprocesses
            # write there regardless of the process CWD; thread-safe under the web
            # server, and avoids polluting the user's CWD).
            temp_prefix = str(work_path / "transcript_temp")

            if not force_whisper:
                # List available subs (only in verbose mode)
                if log.VERBOSITY >= 2 and not stdout_mode:
                    info("Available subtitles:")
                    run(["yt-dlp", "--list-subs", url], check=False)

                # Strategy: manual (lang variants → fallback) → auto (same) → whisper
                lang_variants = get_lang_variants(lang)
                if lang.split("-")[0] != fallback_lang:
                    lang_variants.extend(get_lang_variants(fallback_lang))
                downloaded = False

                for variant in lang_variants:
                    info(f"Trying subtitles ({variant})...")
                    if try_download_subtitle(
                        url, temp_prefix, variant,
                        work_dir=work_path, try_both=True,
                    ):
                        downloaded = True
                        success("Subtitles downloaded!")
                        break

                if downloaded:
                    vtt_files = list(work_path.glob("transcript_temp*.vtt"))
                    if vtt_files:
                        final_vtt = work_path / f"{video_title}.vtt"
                        vtt_files[0].rename(final_vtt)
                        _, summary_md = _render_output(
                            final_vtt,
                            {"title": video_title, "url": url, "duration": video_duration, "whisper": False, "channel": metadata.get("channel", ""), "upload_date": metadata.get("upload_date", "")},
                            fmt, stdout_mode, timestamps, chunk_size,
                            summarize, summarize_cmd, summarize_prompt, summarize_timeout, keep_vtt,
                            output_dir=final_output_dir,
                        )
                        return (video_title, summary_md, video_info)

                warn("No subtitles available.")
            else:
                warn("Forcing Whisper transcription (--whisper flag).")

            # Last resort: Whisper (reuse video_info to avoid a duplicate yt-dlp call)
            if not transcribe_with_whisper(
                url, video_title, model=whisper_model, language=lang,
                keep_audio=keep_audio, download_dir=whisper_dir,
                device=whisper_device, quiet=stdout_mode or log.VERBOSITY == 0,
                video_info=video_info,
                work_dir=work_path,
                keep_audio_dir=final_output_dir if keep_audio else None,
            ):
                raise TranscriptError(
                    "Could not get transcript. The video may not have subtitles "
                    "and transcription was not performed."
                )

            # Post-process Whisper output
            vtt_file = work_path / f"{video_title}.vtt"
            if vtt_file.exists():
                _, summary_md = _render_output(
                    vtt_file,
                    {"title": video_title, "url": url, "duration": video_duration, "whisper": True, "channel": metadata.get("channel", ""), "upload_date": metadata.get("upload_date", "")},
                    fmt, stdout_mode, timestamps, chunk_size,
                    summarize, summarize_cmd, summarize_prompt, summarize_timeout, keep_vtt,
                    output_dir=final_output_dir,
                )
                return (video_title, summary_md, video_info)

        return (video_title, None, video_info)
    finally:
        if work_ctx is not None:
            work_ctx.cleanup()
