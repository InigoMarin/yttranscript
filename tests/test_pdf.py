"""Tests for yttranscript.pdf: markdown to PDF conversion."""

from __future__ import annotations

import pytest

from yttranscript.pdf import markdown_to_pdf


def test_pdf_creates_valid_file(tmp_path):
    """markdown_to_pdf writes a valid PDF file."""
    pytest.importorskip("weasyprint")
    pytest.importorskip("markdown")

    md = "# Title\n\nThis is a **bold** paragraph.\n\n- Item 1\n- Item 2\n"
    out = tmp_path / "output.pdf"
    markdown_to_pdf(md, out)

    assert out.exists()
    # PDF magic bytes: %PDF-
    assert out.read_bytes()[:5] == b"%PDF-"


def test_pdf_renders_headers_and_lists(tmp_path):
    """Headers and bullet lists are converted to PDF content."""
    pytest.importorskip("weasyprint")
    pytest.importorskip("markdown")

    md = "# My Header\n\n## Subsection\n\n- First\n- Second\n\nSome `code` here."
    out = tmp_path / "test.pdf"
    markdown_to_pdf(md, out)

    assert out.exists()
    assert out.stat().st_size > 500  # PDFs have overhead


def test_pdf_empty_markdown(tmp_path):
    """Empty markdown still produces a valid (if minimal) PDF."""
    pytest.importorskip("weasyprint")
    pytest.importorskip("markdown")

    out = tmp_path / "empty.pdf"
    markdown_to_pdf("", out)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"


def test_pdf_handles_special_characters(tmp_path):
    """Unicode and special characters are preserved in PDF."""
    pytest.importorskip("weasyprint")
    pytest.importorskip("markdown")

    md = "# Título en Español\n\nTexto con ñ, ü, y emojis: 🎉\n\n— em dash —"
    out = tmp_path / "unicode.pdf"
    markdown_to_pdf(md, out)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"
