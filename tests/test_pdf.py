"""Tests for yttranscript.pdf: markdown to PDF conversion via Pandoc + Typst."""

from __future__ import annotations

import shutil

import pytest

from yttranscript.pdf import markdown_to_pdf


def _has_deps():
    return shutil.which("pandoc") and shutil.which("typst")


pytestmark = pytest.mark.skipif(
    not _has_deps(), reason="pandoc and typst required"
)


def test_pdf_creates_valid_file(tmp_path):
    md = "# Title\n\nThis is a **bold** paragraph.\n\n- Item 1\n- Item 2\n"
    out = tmp_path / "output.pdf"
    markdown_to_pdf(md, out)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"


def test_pdf_renders_headers_and_lists(tmp_path):
    md = "# My Header\n\n## Subsection\n\n- First\n- Second\n\nSome `code` here."
    out = tmp_path / "test.pdf"
    markdown_to_pdf(md, out)

    assert out.exists()
    assert out.stat().st_size > 500


def test_pdf_empty_markdown(tmp_path):
    out = tmp_path / "empty.pdf"
    markdown_to_pdf("", out)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"


def test_pdf_handles_special_characters(tmp_path):
    md = "# Título en Español\n\nTexto con ñ, ü, y emojis: 🎉\n\n— em dash —"
    out = tmp_path / "unicode.pdf"
    markdown_to_pdf(md, out)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"


def test_pdf_with_video_info(tmp_path):
    md = "Hello world transcript content here."
    out = tmp_path / "meta.pdf"
    video_info = {
        "title": "Test Video",
        "url": "https://youtube.com/watch?v=abc123",
        "duration": 125,
        "whisper": False,
    }
    markdown_to_pdf(md, out, video_info=video_info)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"
    assert out.stat().st_size > 500


def test_pdf_with_video_info_long_duration(tmp_path):
    md = "Content"
    out = tmp_path / "long.pdf"
    video_info = {
        "title": "Long Video",
        "url": "https://youtube.com/watch?v=xyz",
        "duration": 3661,
        "whisper": True,
    }
    markdown_to_pdf(md, out, video_info=video_info)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"
