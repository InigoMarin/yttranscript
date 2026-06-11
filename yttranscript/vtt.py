"""VTT parsing and conversion to text/json. Pure module (no internal deps)."""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Optional


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
    text = html.unescape(text)
    return text.strip()


def parse_vtt(vtt_path: Path):
    """Parse a VTT file, yielding (start_seconds, [cleaned_lines]) per cue.

    Handles WEBVTT headers, timestamp lines, cue identifiers, HTML tags,
    and entity decoding. Each yield is one cue block (blank-line-separated).
    """
    current_start: Optional[int] = None
    cue_lines: list[str] = []

    with open(vtt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                if current_start is not None and cue_lines:
                    cleaned = [_clean_vtt_text(l) for l in cue_lines]
                    cleaned = [c for c in cleaned if c]
                    if cleaned:
                        yield (current_start, cleaned)
                    cue_lines = []
                    current_start = None
                continue
            if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            if "-->" in line:
                current_start = _vtt_time_to_seconds(line.split("-->")[0])
                cue_lines = []
                continue
            if current_start is not None:
                cue_lines.append(line)

    if current_start is not None and cue_lines:
        cleaned = [_clean_vtt_text(l) for l in cue_lines]
        cleaned = [c for c in cleaned if c]
        if cleaned:
            yield (current_start, cleaned)


def vtt_to_json(vtt_path: Path, video_info: dict, chunk_size: int = 30) -> str:
    """Convert VTT to JSON with chunked text for RAG ingestion."""
    cues = [(start, " ".join(lines)) for start, lines in parse_vtt(vtt_path)]

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
        "channel": video_info.get("channel", ""),
        "upload_date": video_info.get("upload_date", ""),
        "source": "whisper" if video_info.get("whisper") else "subtitles",
        "chunk_size": chunk_size,
        "chunks": chunks,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def format_video_header(video_info: dict) -> str:
    """Format video metadata as a Markdown header with separator line."""
    from .util import format_duration

    duration_str = format_duration(video_info.get("duration", 0))
    channel = video_info.get("channel", "")
    upload_date = video_info.get("upload_date", "")
    lines = [
        f"# {video_info.get('title', 'unknown')}",
        "",
        f"**URL:** {video_info.get('url', 'unknown')}  ",
        f"**Channel:** {channel}  " if channel else "",
        f"**Upload Date:** {upload_date}  " if upload_date else "",
        f"**Duration:** {duration_str}  ",
        f"**Transcribed:** {'Whisper' if video_info.get('whisper') else 'YouTube subtitles'}",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def _deduped_cues(vtt_path: Path) -> list[tuple[int, str]]:
    """Return deduplicated (start_seconds, text) pairs from VTT cues."""
    seen: set[str] = set()
    result: list[tuple[int, str]] = []
    for start, cue_lines in parse_vtt(vtt_path):
        for text in cue_lines:
            if text not in seen:
                seen.add(text)
                result.append((start, text))
    return result


def _vtt_to_plain(vtt_path: Path, video_info: Optional[dict] = None, timestamps: bool = False) -> str:
    """Convert VTT to plain text string, deduplicating lines."""
    cues = _deduped_cues(vtt_path)
    if timestamps:
        lines = [f"[{_seconds_to_ts(s)}] {t}" for s, t in cues]
    else:
        lines = [t for _, t in cues]

    result = ""
    if video_info:
        result = format_video_header(video_info)
    result += "\n".join(lines) + "\n"
    return result


def vtt_to_text(vtt_path: Path, output_path: Path, video_info: Optional[dict] = None, timestamps: bool = False) -> None:
    """Convert VTT to plain text file, deduplicating lines."""
    output_path.write_text(_vtt_to_plain(vtt_path, video_info, timestamps), encoding="utf-8")


def vtt_to_stdout(vtt_path: Path, video_info: Optional[dict] = None, timestamps: bool = False) -> None:
    """Convert VTT to plain text and print to stdout."""
    sys.stdout.write(_vtt_to_plain(vtt_path, video_info, timestamps))


def extract_vtt_plain_text(vtt_path: Path) -> str:
    """Extract clean plain text from VTT (for piping to summarizer)."""
    return " ".join(t for _, t in _deduped_cues(vtt_path))


def _vtt_ts_to_ms(ts: str) -> int:
    """Convert VTT timestamp 'HH:MM:SS.mmm' to milliseconds."""
    ts = ts.strip().split()[0]
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        return 0
    sec_parts = s.split(".")
    whole_sec = int(sec_parts[0])
    milli = int(sec_parts[1]) if len(sec_parts) > 1 and sec_parts[1].isdigit() else 0
    return int(h) * 3_600_000 + int(m) * 60_000 + whole_sec * 1_000 + milli


def _ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT timestamp 'HH:MM:SS,mmm'."""
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) // 1_000
    milli = ms % 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def vtt_to_srt(vtt_path: Path) -> str:
    """Convert VTT to SRT subtitle format."""
    cues: list[tuple[int, int, list[str]]] = []
    current_start: Optional[int] = None
    current_end: Optional[int] = None
    cue_lines: list[str] = []

    with open(vtt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                if current_start is not None and cue_lines:
                    cleaned = [_clean_vtt_text(l) for l in cue_lines]
                    cleaned = [c for c in cleaned if c]
                    if cleaned:
                        cues.append((current_start, current_end or 0, cleaned))
                    cue_lines = []
                    current_start = None
                    current_end = None
                continue
            if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            if "-->" in line:
                parts = line.split("-->", 1)
                current_start = _vtt_ts_to_ms(parts[0])
                current_end = _vtt_ts_to_ms(parts[1]) if len(parts) > 1 else None
                cue_lines = []
                continue
            if current_start is not None:
                cue_lines.append(line)

    if current_start is not None and cue_lines:
        cleaned = [_clean_vtt_text(l) for l in cue_lines]
        cleaned = [c for c in cleaned if c]
        if cleaned:
            cues.append((current_start, current_end or 0, cleaned))

    deduped: list[tuple[int, int, list[str]]] = []
    last_text = ""
    for start, end, lines in cues:
        text = "\n".join(lines)
        if text != last_text:
            deduped.append((start, end, lines))
            last_text = text

    srt_blocks: list[str] = []
    for i, (start, end, lines) in enumerate(deduped, 1):
        end_ms = end if end > start else start + 3000
        srt_blocks.append(str(i))
        srt_blocks.append(f"{_ms_to_srt_time(start)} --> {_ms_to_srt_time(end_ms)}")
        srt_blocks.extend(lines)
        srt_blocks.append("")

    return "\n".join(srt_blocks)
