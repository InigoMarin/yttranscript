"""Main transcript processing pipeline."""

from __future__ import annotations

import dataclasses
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
from .summarize import summarize as do_summarize
from .pdf import markdown_to_pdf, markdown_to_epub, markdown_to_docx
from .ytdlp import (
    ensure_yt_dlp,
    get_video_metadata,
    list_subs,
    try_download_subtitle,
    get_lang_variants,
    NetworkOpts,
    NO_NETWORK,
    EJS_HINT,
    looks_like_unsolved_n_challenge,
)
from . import db as cache_db


@dataclasses.dataclass
class VideoInfo:
    """Standard metadata container for a processed video."""
    title: str
    url: str
    duration: int = 0
    size: int = 0
    channel: str = ""
    upload_date: str = ""
    language: str = ""
    source: str = "subtitles"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


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
    no_save: bool = False,
    summarize_backend: str = "cmd",
    summarize_api_url: Optional[str] = None,
    summarize_api_model: Optional[str] = None,
    summarize_api_key: Optional[str] = None,
) -> Optional[tuple[Path, Optional[str]]]:
    """Render VTT to final output: summarize, stdout, or file in output_dir.

    Returns a tuple of (output_file_or_None, summary_markdown_or_None).
    summary_markdown is populated only when summarize=True and a file is saved.
    """
    if summarize:
        if summarize_backend == "api":
            if not summarize_api_url:
                raise TranscriptError(
                    "--summarize with backend 'api' requires summarize_api_url in config "
                    "or --summarize-api-url flag."
                )
            target = f"API: {summarize_api_url} (model: {summarize_api_model})"
        else:
            if not summarize_cmd:
                raise TranscriptError(
                    "--summarize with backend 'cmd' requires summarize_cmd in config "
                    "or --summarize-cmd flag."
                )
            target = f"command: {summarize_cmd}"
        info("Extracting text for summarization...")
        text = extract_vtt_plain_text(vtt_path)
        vtt_path.unlink(missing_ok=True)
        success(f"Sending transcript to {target}")
        summary = do_summarize(
            text,
            backend=summarize_backend,
            cmd=summarize_cmd,
            prompt=summarize_prompt or "",
            timeout=summarize_timeout,
            api_url=summarize_api_url,
            api_model=summarize_api_model,
            api_key=summarize_api_key,
        )
        if not summary:
            raise TranscriptError("Summarization failed.")
        if no_save:
            vtt_path.unlink(missing_ok=True)
            return (None, summary)
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


def _maybe_cache(
    url: str,
    video_title: str,
    video_info: dict,
    metadata: dict,
    lang: str,
    source: str,
    fmt: str,
    stdout_mode: bool,
    use_cache: bool,
    output_dir: Path,
    content: str | None = None,
) -> None:
    """Save transcript to cache DB.

    ``content`` is the transcript text.  If not provided directly, the
    function tries to read it from ``output_dir/{video_title}.txt``.
    """
    if not use_cache or stdout_mode:
        return
    vid = cache_db.extract_video_id(url)
    if not vid:
        return

    # Cache the transcript text.
    if content is None:
        out_file = output_dir / f"{video_title}.txt"
        if fmt == "txt" and out_file.exists():
            content = out_file.read_text(encoding="utf-8")
    if content:
        cache_db.save_transcript(
            video_id=vid,
            url=url,
            title=video_title,
            channel=video_info.get("channel", ""),
            channel_url="",
            duration=video_info.get("duration", 0),
            upload_date=video_info.get("upload_date", ""),
            language=lang,
            source=source,
            fmt="txt",
            content=content,
        )


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
    use_cache: bool = True,
    skip_cached: bool = False,
    no_save: bool = False,
    summarize_backend: str = "cmd",
    summarize_api_url: Optional[str] = None,
    summarize_api_model: Optional[str] = None,
    summarize_api_key: Optional[str] = None,
    network: Optional[NetworkOpts] = None,
) -> Optional[tuple[str, Optional[str], dict, Optional[Path]]]:
    """Main processing pipeline. Returns (video_title, summary_markdown, video_info, output_path) or None.

    `output_path` is the absolute path to the rendered transcript file, or None
    when no file was produced (e.g. --stdout, --no-save, or --list-subs).

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
                list_subs(url, network=network)
                return None

            # Single yt-dlp call for all metadata (language, title, duration, size)
            info("Fetching video metadata...")
            metadata = get_video_metadata(url, network=network)

            if metadata.get("is_live"):
                raise TranscriptError(
                    "This is a live stream. Subtitles are not available until "
                    "the stream ends. Try again after the broadcast finishes."
                )

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
            video_info = VideoInfo(
                duration=metadata["duration"],
                size=metadata["size"],
                title=metadata["title"],
                channel=metadata.get("channel", ""),
                upload_date=metadata.get("upload_date", ""),
                url=url,
                language=lang,
            )

            # --- Cache lookup: skip download if we already have this transcript ---
            if use_cache and not stdout_mode:
                vid = cache_db.extract_video_id(url)
                if vid:
                    cached = cache_db.get_cached(vid, "txt", lang, timestamps=timestamps)
                    if cached:
                        if skip_cached:
                            info(f"Already in cache: {video_title}")
                            return None
                        content, cached_info = cached
                        if summarize:
                            info("Found transcript in cache — skipping download.")
                            if summarize_backend == "api":
                                target = f"API: {summarize_api_url} (model: {summarize_api_model})"
                            else:
                                target = f"command: {summarize_cmd}"
                            success(f"Sending cached transcript to {target}")
                            summary = do_summarize(
                                content,
                                backend=summarize_backend,
                                cmd=summarize_cmd,
                                prompt=summarize_prompt or "",
                                timeout=summarize_timeout,
                                api_url=summarize_api_url,
                                api_model=summarize_api_model,
                                api_key=summarize_api_key,
                            )
                            if not summary:
                                raise TranscriptError("Summarization failed.")
                            final_output_dir.mkdir(parents=True, exist_ok=True)
                            full_text = format_video_header(video_info.to_dict()) + summary + "\n"
                            safe_title = sanitize_filename(video_info.title)
                            if fmt == "pdf":
                                out = final_output_dir / f"{safe_title}.pdf"
                                markdown_to_pdf(summary, out, video_info=video_info.to_dict())
                            elif fmt == "epub":
                                out = final_output_dir / f"{safe_title}.epub"
                                markdown_to_epub(summary, out, video_info=video_info.to_dict())
                            elif fmt == "docx":
                                out = final_output_dir / f"{safe_title}.docx"
                                markdown_to_docx(summary, out, video_info=video_info.to_dict())
                            else:
                                out = final_output_dir / f"{safe_title}.txt"
                                out.write_text(full_text, encoding="utf-8")
                            success(f"Saved: {out}")
                            return (video_title, summary, video_info.to_dict(), out)
                        elif fmt == "txt":
                            info("Found in cache — skipping download.")
                            out = final_output_dir / f"{video_title}.txt"
                            final_output_dir.mkdir(parents=True, exist_ok=True)
                            out.write_text(content, encoding="utf-8")
                            success(f"Saved (cached): {out}")
                            return (video_title, None, video_info.to_dict(), out)

            # Intermediate files go into work_path (absolute paths so subprocesses
            # write there regardless of the process CWD; thread-safe under the web
            # server, and avoids polluting the user's CWD).
            temp_prefix = str(work_path / "transcript_temp")

            if not force_whisper:
                # List available subs (only in verbose mode)
                if log.VERBOSITY >= 2 and not stdout_mode:
                    info("Available subtitles:")
                    run(["yt-dlp", "--list-subs",
                         *(network or NO_NETWORK).to_ytdlp_args(), url], check=False)

                # Strategy: manual (lang variants → fallback) → auto (same) → whisper
                lang_variants = get_lang_variants(lang)
                if lang.split("-")[0] != fallback_lang:
                    lang_variants.extend(get_lang_variants(fallback_lang))
                downloaded = False

                for variant in lang_variants:
                    info(f"Trying subtitles ({variant})...")
                    if try_download_subtitle(
                        url, temp_prefix, variant,
                        work_dir=work_path, try_both=True, network=network,
                    ):
                        downloaded = True
                        success("Subtitles downloaded!")
                        break

                if downloaded:
                    vtt_files = list(work_path.glob("transcript_temp*.vtt"))
                    if vtt_files:
                        final_vtt = work_path / f"{video_title}.vtt"
                        vtt_files[0].rename(final_vtt)
                        # Extract transcript text for caching before _render_output consumes the VTT.
                        cache_text = None
                        if use_cache and not stdout_mode:
                            try:
                                cache_text = extract_vtt_plain_text(final_vtt)
                            except Exception:
                                pass
                        out_path, summary_md = _render_output(
                            final_vtt,
                            video_info.to_dict(),
                            fmt, stdout_mode, timestamps, chunk_size,
                            summarize, summarize_cmd, summarize_prompt, summarize_timeout, keep_vtt,
                            output_dir=final_output_dir, no_save=no_save,
                            summarize_backend=summarize_backend,
                            summarize_api_url=summarize_api_url,
                            summarize_api_model=summarize_api_model,
                            summarize_api_key=summarize_api_key,
                        )
                        _maybe_cache(url, video_title, video_info.to_dict(), metadata, lang, "subtitles", fmt, stdout_mode, use_cache, final_output_dir, content=cache_text)
                        return (video_title, summary_md, video_info.to_dict(), out_path)

                warn("No subtitles available.")

                # Diagnose the most common cause of "metadata empty + no
                # subs on every video": an unsolved YouTube n challenge
                # (missing yt-dlp-ejs / wrong --js-runtimes). Independent
                # of datacenter-IP blocking; see README's VPS section.
                if looks_like_unsolved_n_challenge(metadata):
                    warn(EJS_HINT)
            else:
                warn("Forcing Whisper transcription (--whisper flag).")

            # Last resort: Whisper (reuse video_info to avoid a duplicate yt-dlp call)
            if not transcribe_with_whisper(
                url, video_title, model=whisper_model, language=lang,
                keep_audio=keep_audio, download_dir=whisper_dir,
                device=whisper_device, quiet=stdout_mode or log.VERBOSITY == 0,
                video_info=video_info.to_dict(),
                work_dir=work_path,
                keep_audio_dir=final_output_dir if keep_audio else None,
                network=network,
            ):
                raise TranscriptError(
                    "Could not get transcript. The video may not have subtitles "
                    "and transcription was not performed."
                )

            # Post-process Whisper output
            vtt_file = work_path / f"{video_title}.vtt"
            if vtt_file.exists():
                # Extract transcript text for caching before _render_output consumes the VTT.
                cache_text = None
                if use_cache and not stdout_mode:
                    try:
                        cache_text = extract_vtt_plain_text(vtt_file)
                    except Exception:
                        pass
                out_path, summary_md = _render_output(
                    vtt_file,
                    video_info.to_dict(),
                    fmt, stdout_mode, timestamps, chunk_size,
                    summarize, summarize_cmd, summarize_prompt, summarize_timeout, keep_vtt,
                    output_dir=final_output_dir, no_save=no_save,
                    summarize_backend=summarize_backend,
                    summarize_api_url=summarize_api_url,
                    summarize_api_model=summarize_api_model,
                    summarize_api_key=summarize_api_key,
                )
                _maybe_cache(url, video_title, video_info.to_dict(), metadata, lang, "whisper", fmt, stdout_mode, use_cache, final_output_dir, content=cache_text)
                return (video_title, summary_md, video_info.to_dict(), out_path)

        return (video_title, None, video_info.to_dict(), None)
    finally:
        if work_ctx is not None:
            work_ctx.cleanup()
