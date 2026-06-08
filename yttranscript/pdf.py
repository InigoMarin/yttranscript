"""Markdown to PDF conversion via Pandoc + Typst."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
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


def _check_deps() -> None:
    if not shutil.which("pandoc"):
        raise ImportError(
            "PDF output requires 'pandoc'. Install with: pacman -S pandoc"
        )
    if not shutil.which("typst"):
        raise ImportError(
            "PDF output requires 'typst'. Install with: pacman -S typst"
        )


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

    md_content = markdown_text
    if video_info:
        frontmatter = _build_frontmatter(video_info)
        md_content = frontmatter + "\n\n" + markdown_text

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
