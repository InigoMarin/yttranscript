"""Markdown to PDF conversion via Pandoc + Typst."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import re
from pathlib import Path
from typing import Optional

from .log import info

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "transcript.typ"


def _build_frontmatter(video_info: dict) -> str:
    duration = video_info.get("duration", 0)
    if duration:
        hours = duration // 3600
        if hours:
            duration_str = f"{hours}:{(duration % 3600) // 60:02d}:{duration % 60:02d}"
        else:
            duration_str = f"{duration // 60}:{duration % 60:02d}"
    else:
        duration_str = "unknown"

    source = "Whisper" if video_info.get("whisper") else "YouTube subtitles"

    lines = ["---"]
    lines.append(f"title: {video_info.get('title', 'unknown')}")
    url = video_info.get("url", "")
    if url:
        lines.append(f"url: {url}")
    lines.append(f"duration: {duration_str}")
    lines.append(f"source: {source}")
    lines.append("---")
    return "\n".join(lines)


def _format_duration(seconds: int) -> str:
    if not seconds:
        return "unknown"
    hours = seconds // 3600
    if hours:
        return f"{hours}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _check_deps() -> None:
    if not shutil.which("pandoc"):
        raise ImportError(
            "PDF output requires 'pandoc'. Install with: pacman -S pandoc"
        )
    if not shutil.which("typst"):
        raise ImportError(
            "PDF output requires 'typst'. Install with: pacman -S typst"
        )


def _sanitize_markdown(text: str) -> str:
    """Remove/replace markdown constructs unsupported by Typst via Pandoc."""
    text = re.sub(r'^\s*-{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\*{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*_{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'<[^>]+>', '', text)
    return text


def _run_pandoc(md_content: str, output_path: Path) -> None:
    template = _TEMPLATE_PATH if _TEMPLATE_PATH.exists() else None

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(md_content)
        tmp_path = tmp.name

    try:
        cmd = [
            "pandoc", tmp_path,
            "--pdf-engine=typst",
            "-o", str(output_path),
        ]
        if template:
            cmd.extend(["--template", str(template)])
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Pandoc failed: {result.stderr}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def markdown_to_pdf(
    markdown_text: str,
    output_path: Path,
    video_info: Optional[dict] = None,
) -> None:
    """Convert markdown text to a styled PDF file.

    Uses Pandoc with Typst engine. When video_info is provided, generates
    YAML frontmatter for the template to render metadata (title, URL,
    duration, source) separately from the body content.
    """
    _check_deps()
    info("Converting to PDF...")

    md_content = _sanitize_markdown(markdown_text)
    if video_info:
        frontmatter = _build_frontmatter(video_info)
        md_content = frontmatter + "\n\n" + md_content

    _run_pandoc(md_content, output_path)


def markdown_to_merged_pdf(
    sections: list[tuple[dict, str]],
    output_path: Path,
    channel_name: Optional[str] = None,
) -> None:
    """Convert multiple summary sections into a single merged PDF.

    Each section is a tuple of (video_info, summary_markdown).
    Sections are separated by page breaks.
    """
    _check_deps()
    info("Generating merged PDF...")

    title = channel_name or "Transcripts"
    frontmatter_lines = ["---", f"title: {title}", "---"]
    md_parts = ["\n".join(frontmatter_lines)]

    for video_info, summary_md in sections:
        duration = _format_duration(video_info.get("duration", 0))
        source = "Whisper" if video_info.get("whisper") else "YouTube subtitles"
        url = video_info.get("url", "")
        vtitle = video_info.get("title", "unknown")

        section = "\n\n```{=typst}\n#pagebreak()\n```\n\n"
        section += f"# {vtitle}\n\n"
        section += f"**URL:** {url}  \n"
        section += f"**Duration:** {duration}  \n"
        section += f"**Source:** {source}\n\n"
        section += _sanitize_markdown(summary_md)
        md_parts.append(section)

    _run_pandoc("\n".join(md_parts), output_path)
