"""Markdown to PDF/EPUB/DOCX conversion via Pandoc.

PDF uses the Typst engine with an optional template.  EPUB and DOCX only
require Pandoc itself (no Typst).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import re
from pathlib import Path
from typing import Optional

from .log import info
from .util import format_duration

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "transcript.typ"

# Set of output formats that go through Pandoc.
PANDOC_FORMATS = {"pdf", "epub", "docx"}


def _yaml_quote(value: str) -> str:
    """Escape a string for YAML double-quoted scalar.
    
    In YAML double-quoted strings, we only need to escape backslashes and quotes.
    """
    if not value:
        return '""'
    # Escape backslashes first, then double quotes
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_frontmatter(video_info: dict) -> str:
    duration_str = format_duration(video_info.get("duration", 0))

    source = "Whisper" if video_info.get("whisper") else "YouTube subtitles"

    lines = ["---"]
    lines.append(f"title: {_yaml_quote(video_info.get('title', 'unknown'))}")
    url = video_info.get("url", "")
    if url:
        lines.append(f"url: {_yaml_quote(url)}")
    lines.append(f"duration: {duration_str}")
    lines.append(f"source: {source}")
    lines.append("---")
    return "\n".join(lines)


def _check_deps(fmt: str = "pdf") -> None:
    """Verify external dependencies for the given output format.

    All Pandoc-based formats need ``pandoc``.  Only PDF additionally
    requires ``typst``.
    """
    if not shutil.which("pandoc"):
        raise ImportError(
            f"{fmt.upper()} output requires 'pandoc'. "
            "Install with: pacman -S pandoc  (or https://pandoc.org/installing.html)"
        )
    if fmt == "pdf" and not shutil.which("typst"):
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


def _run_pandoc(
    md_content: str,
    output_path: Path,
    fmt: str = "pdf",
    metadata: Optional[dict] = None,
) -> None:
    """Run Pandoc to convert *md_content* into the requested *fmt*.

    *fmt* is one of ``"pdf"``, ``"epub"``, ``"docx"``.  For PDF the Typst
    engine and optional template are used; for EPUB/DOCX Pandoc picks the
    right writer from the output file extension.

    *metadata* is an optional dict of ``{key: value}`` pairs passed as
    ``--metadata key=value`` flags to Pandoc.
    """
    template = _TEMPLATE_PATH if _TEMPLATE_PATH.exists() else None

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(md_content)
        tmp_path = tmp.name

    try:
        cmd = [
            "pandoc", tmp_path,
            "-o", str(output_path),
        ]
        if fmt == "pdf":
            cmd.append("--pdf-engine=typst")
            if template:
                cmd.extend(["--template", str(template)])
        if metadata:
            for key, value in metadata.items():
                cmd.append(f"--metadata={key}={value}")
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
    _check_deps("pdf")
    info("Converting to PDF...")

    md_content = _sanitize_markdown(markdown_text)
    if video_info:
        frontmatter = _build_frontmatter(video_info)
        md_content = frontmatter + "\n\n" + md_content

    _run_pandoc(md_content, output_path, fmt="pdf")


def markdown_to_epub(
    markdown_text: str,
    output_path: Path,
    video_info: Optional[dict] = None,
) -> None:
    """Convert markdown text to an EPUB e-book.

    Uses Pandoc. When video_info is provided, generates YAML frontmatter
    with metadata (title, URL, duration, source) and passes ``--metadata``
    flags for title and author.
    """
    _check_deps("epub")
    info("Converting to EPUB...")

    md_content = _sanitize_markdown(markdown_text)
    meta = None
    if video_info:
        frontmatter = _build_frontmatter(video_info)
        md_content = frontmatter + "\n\n" + md_content
        meta = {
            "title": video_info.get("title", "unknown"),
            "author": "yttranscript",
        }

    _run_pandoc(md_content, output_path, fmt="epub", metadata=meta)


def markdown_to_docx(
    markdown_text: str,
    output_path: Path,
    video_info: Optional[dict] = None,
) -> None:
    """Convert markdown text to a DOCX (Word) document.

    Uses Pandoc. When video_info is provided, generates YAML frontmatter
    with metadata (title, URL, duration, source) and passes ``--metadata``
    flags for title and author.
    """
    _check_deps("docx")
    info("Converting to DOCX...")

    md_content = _sanitize_markdown(markdown_text)
    meta = None
    if video_info:
        frontmatter = _build_frontmatter(video_info)
        md_content = frontmatter + "\n\n" + md_content
        meta = {
            "title": video_info.get("title", "unknown"),
            "author": "yttranscript",
        }

    _run_pandoc(md_content, output_path, fmt="docx", metadata=meta)


def _section_separator(fmt: str) -> str:
    """Return the appropriate page-break markup for the output format."""
    if fmt == "pdf":
        return "\n\n```{=typst}\n#pagebreak()\n```\n\n"
    return "\n\n\\newpage\n\n"


def markdown_to_merged(
    sections: list[tuple[dict, str]],
    output_path: Path,
    fmt: str = "pdf",
    channel_name: Optional[str] = None,
) -> None:
    """Convert multiple summary sections into a single merged document.

    *fmt* is one of ``"pdf"``, ``"epub"``, ``"docx"``.
    Each section is a tuple of (video_info, summary_markdown).
    Sections are separated by page breaks.
    """
    _check_deps(fmt)
    info(f"Generating merged {fmt.upper()}...")

    title = channel_name or "Transcripts"
    frontmatter_lines = ["---", f"title: {_yaml_quote(title)}", "---"]
    md_parts = ["\n".join(frontmatter_lines)]

    sep = _section_separator(fmt)

    for video_info, summary_md in sections:
        duration = format_duration(video_info.get("duration", 0))
        source = "Whisper" if video_info.get("whisper") else "YouTube subtitles"
        url = video_info.get("url", "")
        vtitle = video_info.get("title", "unknown")

        section = sep
        section += f"# {vtitle}\n\n"
        section += f"**URL:** {url}  \n"
        section += f"**Duration:** {duration}  \n"
        section += f"**Source:** {source}\n\n"
        section += _sanitize_markdown(summary_md)
        md_parts.append(section)

    meta = None
    if fmt in ("epub", "docx"):
        meta = {"title": title, "author": "yttranscript"}

    _run_pandoc("\n".join(md_parts), output_path, fmt=fmt, metadata=meta)


def markdown_to_merged_pdf(
    sections: list[tuple[dict, str]],
    output_path: Path,
    channel_name: Optional[str] = None,
) -> None:
    """Backward-compatible wrapper; delegates to :func:`markdown_to_merged`."""
    markdown_to_merged(sections, output_path, fmt="pdf", channel_name=channel_name)
